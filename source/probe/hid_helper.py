"""On-demand capture helper. GUI/normal transports are never elevated.

The authenticated loopback channel accepts only heartbeat/stop. No caller paths,
commands, shell fragments, or file writes are accepted by the elevated process.
"""
import contextlib
import ctypes
import json
import os
from pathlib import Path
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time

from .hid_capture import (MAX_PACKET, linux_devices, linux_metadata, pcap_packets,
                          parse_usbmon, usbpcap_command, validate_source, windows_devices)

MAX_FRAME=3*MAX_PACKET


def send_message(sock,message):
    data=json.dumps(message,ensure_ascii=True,separators=(',',':')).encode('ascii')
    if len(data)>MAX_FRAME:raise ValueError('HID helper message exceeds limits.')
    sock.sendall(struct.pack('!I',len(data))+data)


def receive_message(sock):
    def exact(size):
        result=bytearray()
        while len(result)<size:
            data=sock.recv(size-len(result))
            if not data:raise EOFError('HID helper disconnected.')
            result.extend(data)
        return result
    size=struct.unpack('!I',exact(4))[0]
    if not 0<size<=MAX_FRAME:raise ValueError('Invalid HID helper message length.')
    message=json.loads(exact(size))
    if not isinstance(message,dict):raise ValueError('Invalid HID helper message.')
    return message


def capture_linux(source,send,stop):
    import ctypes.util
    bus,device=validate_source(source,False);bus=int(bus)
    metadata=linux_metadata(source)
    path=Path(f'/dev/usbmon{bus}')
    if not path.exists():
        modprobe=next((p for p in ('/usr/sbin/modprobe','/sbin/modprobe','/usr/bin/modprobe') if Path(p).is_file()),None)
        if modprobe and os.geteuid()==0:subprocess.run([modprobe,'usbmon'],check=True,timeout=15,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if not path.exists():raise OSError('usbmon is unavailable in this kernel. Enable its usbmon module on this system; no download is attempted by Probe.')
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK)
    class Get(ctypes.Structure):_fields_=[('header',ctypes.c_void_p),('data',ctypes.c_void_p),('size',ctypes.c_size_t)]
    libc=ctypes.CDLL(None,use_errno=True);libc.ioctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_void_p];libc.ioctl.restype=ctypes.c_int
    header=ctypes.create_string_buffer(64);data=ctypes.create_string_buffer(MAX_PACKET)
    arg=Get(ctypes.addressof(header),ctypes.addressof(data),MAX_PACKET)
    getx=(1<<30)|(ctypes.sizeof(Get)<<16)|(0x92<<8)|10
    stats=(2<<30)|(8<<16)|(0x92<<8)|3;last_stats=time.monotonic()
    try:
        send(dict(kind='metadata',**metadata));send(dict(kind='ready'))
        while not stop.is_set():
            if not select.select([fd],[],[],.2)[0]:continue
            if libc.ioctl(fd,getx,ctypes.byref(arg))<0:
                code=ctypes.get_errno()
                if code in (11,4):continue
                raise OSError(code,os.strerror(code))
            captured=struct.unpack_from('<I',header.raw,36)[0]
            packet=parse_usbmon(header.raw,data.raw[:min(captured,MAX_PACKET)])
            if packet['bus']==bus and packet['device']==device:
                packet['payload']=packet['payload'].hex();send(dict(kind='packet',packet=packet))
            if time.monotonic()-last_stats>1:
                counts=(ctypes.c_uint32*2)()
                if libc.ioctl(fd,stats,ctypes.byref(counts))==0 and counts[1]:send(dict(kind='warning',message=f'usbmon reported {counts[1]} dropped bus events; capture may be incomplete.'))
                last_stats=time.monotonic()
    finally:os.close(fd)


def capture_windows(source,send,stop):
    root,device=validate_source(source,True);command=usbpcap_command()
    if command is None:raise OSError('USBPcap is not installed. Install the bundled offline driver and restart Windows.')
    # Never capture all/new devices. The address filter is fixed to the user's selection.
    process=subprocess.Popen([str(command),'-d',root,'--devices',str(device),'--inject-descriptors','-s',str(MAX_PACKET),'-b',str(8*1024*1024),'-o','-'],
                             stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
    errors=[]
    def stderr():
        for line in iter(process.stderr.readline,b''):
            if len(errors)<20:errors.append(line.decode('utf-8',errors='replace').strip())
    def cancel():
        stop.wait()
        if process.poll() is None:
            with contextlib.suppress(OSError,ValueError):process.stdin.write(b'q\n');process.stdin.flush()
            try:process.wait(2)
            except subprocess.TimeoutExpired:process.terminate()
    reader=threading.Thread(target=stderr,daemon=True);reader.start()
    canceller=threading.Thread(target=cancel,daemon=True);canceller.start()
    try:
        # First packet validates both the pcap header and the driver startup.
        ready=False
        for packet in pcap_packets(process.stdout):
            if stop.is_set():break
            if not ready:send(dict(kind='ready'));ready=True
            if packet['device']==device:
                packet['payload']=packet['payload'].hex();send(dict(kind='packet',packet=packet))
        if not stop.is_set():raise OSError('USB capture ended. '+ ' '.join(errors)[-1000:])
    except (OSError,ValueError) as exc:
        if not stop.is_set():raise OSError(str(exc)+' '+ ' '.join(errors)[-1000:]) from exc
    finally:
        stop.set()
        if process.poll() is None:
            try:process.wait(3)
            except subprocess.TimeoutExpired:process.kill();process.wait(2)
        for stream in (process.stdin,process.stdout,process.stderr):
            with contextlib.suppress(OSError):stream.close()
        reader.join(1);canceller.join(1)


def helper_main(port,token,action,source):
    if not 1<=port<=65535 or not re.fullmatch('[0-9a-f]{64}',token):raise ValueError('Invalid HID helper channel.')
    if action not in ('list','capture','check'):raise ValueError('Unsupported helper action.')
    if action=='capture':validate_source(source)
    stop=threading.Event()
    with socket.create_connection(('127.0.0.1',port),timeout=10) as sock:
        send_message(sock,dict(token=token));reply=receive_message(sock)
        if reply.get('token')!=token:return
        sock.settimeout(10)
        lock=threading.Lock()
        def send(message):
            with lock:send_message(sock,message)
        def controls():
            try:
                while not stop.is_set():
                    # Parent sends heartbeat every second; EOF/timeout revokes capture.
                    command=receive_message(sock)
                    if command!={'kind':'ping'}:break
                    send(dict(kind='heartbeat'))
            except (OSError,EOFError,ValueError):pass
            finally:stop.set()
        watcher=threading.Thread(target=controls,name='Probe HID watchdog',daemon=True);watcher.start()
        try:
            if action=='check':send(dict(kind='checked',capture_started=False))
            elif action=='list':send(dict(kind='devices',devices=windows_devices() if os.name=='nt' else linux_devices()))
            elif os.name=='nt':capture_windows(source,send,stop)
            else:capture_linux(source,send,stop)
        except Exception as exc:
            with contextlib.suppress(OSError):send(dict(kind='error',message=str(exc)[:2000]))
        finally:
            stop.set()
            with contextlib.suppress(OSError):sock.shutdown(socket.SHUT_RDWR)
            watcher.join(1)


def helper_command(port,token,action,source):
    options=['--hid-helper','--hid-port',str(port),'--hid-token',token,'--hid-action',action]
    if source:options+=['--hid-source',source]
    if getattr(sys,'frozen',False):return [sys.executable,*options]
    return [sys.executable,str(Path(__file__).resolve().parent.parent/'run_probe.py'),*options]


def launch_helper(command,elevate):
    if os.name=='nt' and elevate:
        from ctypes import wintypes
        class SHELLEXECUTEINFO(ctypes.Structure):
            _fields_=[('cbSize',wintypes.DWORD),('fMask',wintypes.ULONG),('hwnd',wintypes.HWND),('lpVerb',wintypes.LPCWSTR),('lpFile',wintypes.LPCWSTR),('lpParameters',wintypes.LPCWSTR),('lpDirectory',wintypes.LPCWSTR),('nShow',ctypes.c_int),('hInstApp',wintypes.HINSTANCE),('lpIDList',ctypes.c_void_p),('lpClass',wintypes.LPCWSTR),('hkeyClass',wintypes.HKEY),('dwHotKey',wintypes.DWORD),('hIcon',wintypes.HANDLE),('hProcess',wintypes.HANDLE)]
        info=SHELLEXECUTEINFO();info.cbSize=ctypes.sizeof(info);info.fMask=0x40|0x400;info.lpVerb='runas';info.lpFile=command[0]
        info.lpParameters=subprocess.list2cmdline(command[1:]);info.nShow=0
        shell=ctypes.WinDLL('shell32',use_last_error=True);shell.ShellExecuteExW.argtypes=[ctypes.POINTER(SHELLEXECUTEINFO)];shell.ShellExecuteExW.restype=wintypes.BOOL
        if not shell.ShellExecuteExW(ctypes.byref(info)):
            code=ctypes.get_last_error()
            if code==1223:raise OSError('Permission request cancelled. Probe remains open without administrator access.')
            raise ctypes.WinError(code)
        # The helper owns no files and exits when the authenticated channel closes.
        return WindowsProcess(info.hProcess)
    if elevate:
        pkexec=shutil.which('pkexec')
        if pkexec:command=[pkexec,*command]
        else:
            terminal=next((p for p in ('/usr/bin/x-terminal-emulator','/usr/bin/xterm') if Path(p).is_file()),None)
            sudo=shutil.which('sudo')
            if not terminal or not sudo:raise OSError('No desktop authentication helper is available. Configure usbmon access for your user, or use a desktop with pkexec. Probe will not download anything.')
            command=[terminal,'-e',sudo,'--',*command]
    return subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000 if os.name=='nt' else 0)


class WindowsProcess:
    def __init__(self,handle):self.handle=handle
    def poll(self):
        value=ctypes.c_ulong();kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        if not kernel.GetExitCodeProcess(self.handle,ctypes.byref(value)):return 1
        return None if value.value==259 else value.value
    def close(self):
        if self.handle:
            kernel=ctypes.WinDLL('kernel32');kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle(self.handle);self.handle=None


class HelperClient:
    def __init__(self):self.sock=None;self.process=None
    def messages(self,action,source,stop,elevate=True):
        import secrets
        token=secrets.token_hex(32)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(4);listener.settimeout(.2)
            command=helper_command(listener.getsockname()[1],token,action,source)
            self.process=launch_helper(command,elevate);deadline=time.monotonic()+120
            try:
                while not stop.is_set():
                    if time.monotonic()>deadline:raise OSError('HID permission request timed out.')
                    try:sock,_=listener.accept()
                    except socket.timeout:
                        if self.process.poll() is not None:raise OSError('HID helper exited or permission was denied. Probe continues without elevation.')
                        continue
                    sock.settimeout(2)
                    try:
                        if receive_message(sock)!={'token':token}:sock.close();continue
                        send_message(sock,dict(token=token))
                    except (OSError,EOFError,ValueError):sock.close();continue
                    self.sock=sock;break
                if self.sock is None:return
                channel=self.sock
                def heartbeat():
                    while not stop.wait(.5):
                        try:send_message(channel,dict(kind='ping'))
                        except (OSError,ValueError):break
                    with contextlib.suppress(OSError):channel.shutdown(socket.SHUT_RDWR)
                beat=threading.Thread(target=heartbeat,daemon=True);beat.start()
                try:
                    self.sock.settimeout(15)
                    while not stop.is_set():
                        # Keep framing intact across timeouts/partial socket reads.
                        message=receive_message(self.sock)
                        if message.get('kind')=='error':raise OSError(message.get('message','HID capture failed.'))
                        yield message
                        if action in ('list','check') and message.get('kind') in ('devices','checked'):return
                except EOFError:
                    if not stop.is_set() and action!='list':raise OSError('HID capture helper disconnected unexpectedly.') from None
                finally:stop.set();beat.join(2)
            finally:self.close()
    def close(self):
        if self.sock:
            with contextlib.suppress(OSError):self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close();self.sock=None
        if self.process and isinstance(self.process,WindowsProcess):self.process.close()
        elif self.process:
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):self.process.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):self.process.wait(timeout=2)
        self.process=None


def discover_devices(allow_elevation=False,stop=None):
    if os.name!='nt':return linux_devices()
    try:return windows_devices()
    except OSError:
        if not allow_elevation or usbpcap_command() is None:raise
    client=HelperClient();stop=stop or threading.Event()
    messages=client.messages('list','',stop)
    try:
        for message in messages:
            if message.get('kind')=='devices':return message['devices']
    finally:messages.close()
    return []
