"""Embed printable codes so invoice printing does not require a CDN."""
import base64

from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing


def invoice_print_codes(invoice_id, public_url):
    value=str(int(invoice_id))
    barcode=createBarcodeDrawing("Code128",value=value,barWidth=1.25,barHeight=40,
        humanReadable=True,quiet=True)
    widget=QrCodeWidget(str(public_url),barLevel="H")
    x1,y1,x2,y2=widget.getBounds()
    qr=Drawing(108,108,transform=[108/(x2-x1),0,0,108/(y2-y1),-x1,-y1])
    qr.add(widget)
    def uri(drawing):
        svg=drawing.asString("svg")
        if isinstance(svg,str):
            svg=svg.encode("utf-8")
        return "data:image/svg+xml;base64,"+base64.b64encode(svg).decode("ascii")
    return {"barcode":uri(barcode),"qr":uri(qr)}
