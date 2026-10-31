"""USB capture formats and local prerequisites. No elevation at import/startup."""
import hashlib
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

INSTALLER='USBPcapSetup-1.5.4.0.exe'
INSTALLER_SHA256='87a7edf9bbbcf07b5f4373d9a192a6770d2ff3add7aa1e276e82e38582ccb622'
MAX_PACKET=1024*1024
USBPCAP_HEADER=struct.Struct('<HQIHBHHBBI')
USBMON_HEADER=struct.Struct('<QBBBBHBBqiiII8siiII')


def resource_root():return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))


def bundled_installer():
    path=resource_root()/'drivers'/'windows'/INSTALLER
    if not path.is_file():raise OSError('Bundled USBPcap installer is missing. Re-extract the complete Probe package.')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=INSTALLER_SHA256:raise OSError('Bundled USBPcap installer checksum failed. Re-extract the original package.')
    return path


def usbpcap_command():
    if os.name!='nt':return None
    import winreg
    roots=[]
    for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\USBPcap',0,winreg.KEY_READ|view) as key:
                roots.append(Path(winreg.QueryValueEx(key,'InstallLocation')[0]))
        except OSError:pass
    # Privileged helper only executes a machine-installed command. Do not resolve
    # executables via PATH or caller-controlled ProgramFiles environment values.
    for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows\CurrentVersion',0,winreg.KEY_READ|view) as key:
                for name in ('ProgramFilesDir','ProgramFilesDir (x86)'):
                    try:roots.append(Path(winreg.QueryValueEx(key,name)[0])/'USBPcap')
                    except OSError:pass
        except OSError:pass
    for root in roots:
        path=root/'USBPcapCMD.exe'
        if path.is_file():return path
    return None


def run_command(args,timeout=15):
    result=subprocess.run([str(a) for a in args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          timeout=timeout,creationflags=0x08000000 if os.name=='nt' else 0)
    if result.returncode:raise OSError(result.stderr.decode('utf-8',errors='replace')[:1000] or 'USB device discovery failed.')
    return result.stdout.decode('utf-8',errors='replace')


def parse_extcap_devices(root, text):
    rows=[];children={}
    for line in text.splitlines():
        if not line.startswith('value '):continue
        d=dict(re.findall(r'\{([^={}]+)=([^{}]*)\}',line));value=d.get('value','')
        if value.isdigit() and d.get('enabled')=='true':rows.append(d)
        elif '_' in value:children.setdefault(value.split('_')[0],[]).append(d.get('display',''))
    return [dict(source=f'{root}:{int(row["value"])}',name=row.get('display','USB device')+
                 (' · '+', '.join(dict.fromkeys(children.get(row['value'],[]))) if children.get(row['value']) else ''),
                 bus=root,device=int(row['value'])) for row in rows if int(row['value'])>0]


def windows_devices():
    command=usbpcap_command()
    if command is None:raise OSError('USBPcap is not installed. Use Install USBPcap (offline), then restart Windows.')
    devices=[]
    for line in run_command([command,'--extcap-interfaces']).splitlines():
        match=re.search(r'\{value=(\\\\\.\\USBPcap\d+)\}',line)
        if match:
            root=match[1];text=run_command([command,'--extcap-interface',root,'--extcap-config'])
            devices.extend(parse_extcap_devices(root,text))
    if not devices:raise OSError('No USB capture devices found. Restart Windows after USBPcap installation, then Refresh devices.')
    return devices


def linux_devices(root=Path('/sys/bus/usb/devices')):
    devices=[]
    for path in sorted(root.glob('*')):
        if ':' in path.name:continue
        try:
            bus=int((path/'busnum').read_text());device=int((path/'devnum').read_text())
            interfaces={}
            for interface in root.glob(path.name+':*'):
                if (interface/'bInterfaceClass').read_text().strip()=='03':
                    interfaces[int((interface/'bInterfaceNumber').read_text(),16)]=[]
            if not interfaces:continue
            label=(path/'product').read_text().strip() if (path/'product').exists() else 'USB HID device'
            vid=(path/'idVendor').read_text().strip();pid=(path/'idProduct').read_text().strip()
            devices.append(dict(source=f'{bus}:{device}',name=f'{label} · {vid}:{pid} · USB {bus}:{device}',bus=bus,device=device))
        except (OSError,ValueError):continue
    return devices


def validate_source(source,windows=None):
    windows=os.name=='nt' if windows is None else windows
    pattern=r'(\\\\\.\\USBPcap[1-9]\d{0,3}):([1-9]\d{0,2})' if windows else r'([1-9]\d{0,3}):([1-9]\d{0,2})'
    match=re.fullmatch(pattern,source)
    if not match or int(match[2])>127:raise ValueError('Choose one USB device from Refresh devices.')
    return match[1],int(match[2])


def linux_metadata(source):
    from .hid_reports import interfaces_from_config
    bus,device=validate_source(source,False);bus=int(bus);interfaces={};descriptors={}
    for path in Path('/sys/bus/usb/devices').glob('*'):
        try:
            if ':' in path.name or int((path/'busnum').read_text())!=bus or int((path/'devnum').read_text())!=device:continue
            config=(path/'descriptors').read_bytes()
            interfaces=interfaces_from_config(config)
            physical=path.resolve()
            for item in Path('/sys/bus/hid/devices').glob('*'):
                resolved=item.resolve()
                if physical not in resolved.parents:continue
                interface=next((p for p in resolved.parents if ':' in p.name and (p/'bInterfaceNumber').exists()),None)
                if interface:
                    number=int((interface/'bInterfaceNumber').read_text(),16)
                    try:descriptors[number]=(item/'report_descriptor').read_bytes().hex()
                    except OSError:pass
            return dict(interfaces={str(k):sorted(v) for k,v in interfaces.items()},descriptors=descriptors)
        except (OSError,ValueError):continue
    raise OSError('Selected USB device disappeared. Refresh devices and select it again.')


def parse_usbpcap(data, timestamp):
    if len(data)<USBPCAP_HEADER.size:raise ValueError('Truncated USBPcap header.')
    size,ident,status,function,info,bus,device,endpoint,transfer,length=USBPCAP_HEADER.unpack_from(data)
    if size<USBPCAP_HEADER.size or size>len(data) or length>MAX_PACKET:raise ValueError('Invalid USBPcap packet size.')
    stage='complete' if info&1 else 'submit';payload=data[size:size+length];setup=b''
    if transfer==2:
        if size<28:raise ValueError('Missing USBPcap control stage.')
        control_stage=data[27]
        if control_stage==0:
            if len(payload)<8:return None
            setup=payload[:8];payload=payload[8:];stage='submit'
        elif control_stage==3:stage='complete'
        else:return None # USBPcap before 1.5 uses a different control encoding.
    return dict(id=ident,time=timestamp,status=status,bus=bus,device=device,endpoint=endpoint,
                transfer={1:'interrupt',2:'control',3:'bulk',0:'isochronous'}.get(transfer,'unknown'),
                stage=stage,payload=payload,setup=setup.hex(),length=max(0,length-len(setup)))


def parse_usbmon(header, data):
    if len(header)!=64:raise ValueError('Expected a 64-byte usbmon header.')
    ident,typ,transfer,endpoint,device,bus,setup_flag,data_flag,sec,usec,status,length,captured,setup,*_=USBMON_HEADER.unpack(header)
    if captured>MAX_PACKET or captured>len(data):raise ValueError('Truncated usbmon data.')
    return dict(id=ident,time=sec+usec/1e6,status=status,bus=bus,device=device,endpoint=endpoint,
                transfer={1:'interrupt',2:'control',3:'bulk',0:'isochronous'}.get(transfer,'unknown'),
                stage={83:'submit',67:'complete',69:'error'}.get(typ,'unknown'),
                payload=data[:captured] if data_flag==0 else b'',setup=setup.hex() if setup_flag==0 and transfer==2 else '',length=length)


def read_exact(stream,size):
    chunks=bytearray()
    while len(chunks)<size:
        chunk=stream.read(size-len(chunks))
        if not chunk:
            if not chunks:return None
            raise OSError('Capture stream ended in a packet.')
        chunks.extend(chunk)
    return bytes(chunks)


def pcap_packets(stream):
    header=read_exact(stream,24)
    if header is None:raise OSError('USBPcap did not produce capture data. Check driver installation and permissions.')
    magics={b'\xd4\xc3\xb2\xa1':('<',1e6),b'\xa1\xb2\xc3\xd4':('>',1e6),b'\x4d\x3c\xb2\xa1':('<',1e9),b'\xa1\xb2\x3c\x4d':('>',1e9)}
    if header[:4] not in magics:raise ValueError('Invalid USBPcap pcap header.')
    endian,scale=magics[header[:4]]
    if struct.unpack_from(endian+'I',header,20)[0]!=249:raise ValueError('Capture is not USBPcap (link type 249).')
    while (record:=read_exact(stream,16)) is not None:
        sec,fraction,size,original=struct.unpack(endian+'IIII',record)
        if size>MAX_PACKET or size<USBPCAP_HEADER.size:raise ValueError('USB capture packet exceeds limits.')
        packet=read_exact(stream,size)
        if packet is None:raise OSError('Capture packet payload is missing.')
        parsed=parse_usbpcap(packet,sec+fraction/scale)
        if parsed:yield parsed
