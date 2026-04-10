# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) Wan Buffer Services (<https://wanbuffer.com/>).
#
#    For Module Support : support@wanbuffer.com  or Call : +91 9638442270
#
##############################################################################
from odoo import api, fields, models, _
from odoo.exceptions import UserError


# from tomlkit import string


class ScandocManager(models.Model):
    """ This model represents scandoc.manager."""
    _name = 'scandoc.manager'
    _description = 'ScandocManager'

    name = fields.Char(string='Customer Name', default="/",
                       required=True, copy=False,
                       readonly=True, index=True)
    active = fields.Boolean(default=True, string="Active")
    purchased_credit = fields.Integer(string="Purchased Credit",readonly=True)
    used_credit = fields.Integer(string="Used Credit")
    remaining_credit = fields.Integer(string="Remaining Credit")
    purchase_date = fields.Date(string="Purchase Date",
                                default=lambda self: fields.Date.today())

    _sql_constraints = [
        ('unique_name', 'unique(name)', 'Customer Name must be unique.')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'scandoc.manager'
                ) or '/'
        return super().create(vals_list)

    def action_check_auth_and_scan(self):
        """
        Check ScanDoc authentication and open scan wizard if valid.
        This method ensures the menu is only functional with proper authentication.
        """
        # Check if auth key is configured
        auth_key = self.env['ir.config_parameter'].sudo().get_param(
            'wb_scandoc_integration.scandoc_auth_key'
        )
        
        if not auth_key:
            raise UserError(_(
                "ScanDoc Authentication Required!\n\n"
                "No authentication key is configured for ScanDoc integration.\n\n"
                "Please follow these steps:\n"
                "1. Go to Settings → General Settings\n"
                "2. Find the 'ScanDoc Integration' section\n"
                "3. Click 'Get Authentication Key' to obtain your key\n"
                "4. Enter and verify your authentication key\n\n"
                "Once configured, you'll be able to access the Scan Document feature."
            ))
        
        # Check if auth key is validated
        company = self.env.company
        if not company.is_auth_key_validated:
            raise UserError(_(
                "ScanDoc Authentication Key Not Validated!\n\n"
                "Your authentication key needs to be verified before you can use ScanDoc features.\n\n"
                "Please follow these steps:\n"
                "1. Go to Settings → General Settings\n"
                "2. Find the 'ScanDoc Integration' section\n"
                "3. Click 'Verify Authentication Key' to validate your key\n\n"
                "If the key is invalid, you may need to obtain a new one from the ScanDoc portal."
            ))
        
        # If we reach here, authentication is valid - open the scan wizard
        return {
            'type': 'ir.actions.act_window',
            'name': 'Scan Document',
            'res_model': 'resume.parser.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_doc_type': 'VendorBill'}
        }


class TransactionHistory(models.Model):
    """ This model represents scandoc.manager."""
    _name = 'transaction.history'
    _description = 'Transaction History'


    invoice_name = fields.Char(string="Invoice Name")
    quantity = fields.Char(string="Quantity")
    purchase_date_transaction = fields.Datetime(string="Purchase Date")
    total = fields.Float(string="Total")
    status = fields.Char(string="Status")
    company_id = fields.Many2one('res.company', string="Company")


class AuditHistory(models.Model):
    """ This model represents scandoc.manager."""
    _name = 'audit.history'
    _description = 'Audit History'

    document_id = fields.Char(string="Document ID")
    document_name = fields.Char(string="Document Name")
    auditlog_date = fields.Datetime(string="Date")
    status = fields.Char(string="Status")
    company_id = fields.Many2one('res.company', string="Company")