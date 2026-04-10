# -*- coding: utf-8 -*-
from odoo import models,fields


class StockPicking(models.Model):
    _inherit = "stock.picking"


    challan_number = fields.Char(string="Chalan Number")
    vendor_gst_number = fields.Char(string="Vendor GST/vat no.")
    vehicle_number = fields.Char(string="Vehicle Number")
    transport_doc_no = fields.Char(string="Transport Doc No")
    transport_name = fields.Char(string="Transport Name")
    dispatch_location = fields.Char(string="Dispatch Location")


    def action_parse_vendor_bill_receipt(self):
        """
        Button action to open the scandoc wizard.
        Used to parse CV and fill in related fields automatically.
        """
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "wb_scandoc_inventory.action_scandoc_po_wizard"
        )
        return action
