"""Picklable, side-effect-free sequence work executed outside transport/GIL."""


def render(spec,values):return spec.render(values)


def extract(items,data):return {item.name:item.read(data) for item in items}
