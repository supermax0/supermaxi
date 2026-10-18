"""Add the courier receipt to selected invoice themes without replacing their layout."""
from html import escape
from html.parser import HTMLParser
from utils.shipping_barcodes import get_shipping_barcodes_list


class _ReceiptLocation(HTMLParser):
    """Find an insertion point while preserving every byte of the selected theme."""
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.lines=[0]+[index+1 for index,char in enumerate(source) if char=='\n']
        self.nodes=[];self.stack=[];self.marked=False

    def absolute_position(self):
        line,column=self.getpos()
        return self.lines[line-1]+column

    def handle_starttag(self, tag, attrs):
        values=dict(attrs);classes=set((values.get('class') or '').split())
        self.marked=self.marked or 'data-finora-shipping-receipt' in values
        node={'tag':tag,'open':self.absolute_position()+len(self.get_starttag_text()),'close':None,
            'customer':values.get('data-section')=='customer' or bool(classes & {'customer-info-box','customer-info','client-info'}),
            'root':tag=='body' or bool(classes & {'invoice-container','invoice','page-shell'})}
        self.nodes.append(node)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}: self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.marked=self.marked or 'data-finora-shipping-receipt' in dict(attrs)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index]['tag']==tag:
                self.stack[index]['close']=self.absolute_position()
                del self.stack[index:]
                break


def attach_shipping_receipt(html, order):
    numbers = get_shipping_barcodes_list(order)
    if not numbers:
        return html
    document = _ReceiptLocation(html);document.feed(html);document.close()
    if document.marked:
        return html
    customer = next((node for node in document.nodes if node['customer'] and node['close'] is not None),None)
    root = customer or next((node for node in document.nodes if node['root'] and node['tag']!='body'),None) or next((node for node in document.nodes if node['tag']=='body'),None)
    if root is None:
        return html
    block = '<div data-finora-shipping-receipt dir="rtl" style="font-size:11px;line-height:1.6;margin:6px 0;overflow-wrap:anywhere;break-inside:avoid"><strong>رقم وصل / بوليصة النقل: </strong><span dir="ltr" style="unicode-bidi:isolate">'+escape(' | '.join(numbers))+'</span>'
    company = getattr(order, 'shipping_company', None)
    if company is not None and getattr(company, 'name', None):
        block += '<span> · '+escape(company.name)+'</span>'
    block += '</div>'
    position = customer['close'] if customer is not None else root['open']
    return html[:position]+block+html[position:]
