# -*- coding: utf-8 -*-
"""
This module extends the res.company model to add configuration fields
for the ScanDoc integration.

These fields allow companies to manage their ScanDoc integration settings
directly from the company configuration screen in Odoo.
"""


from odoo import fields, models, api


class ResCompany(models.Model):
    """
    Inherits the res.company model to introduce ScanDoc-specific configuration fields.

    These fields help in enabling or disabling scanning features and handling
    authentication and messages for ScanDoc integrations.
    """

    _inherit = "res.company"

    scandoc_auth_key = fields.Char(string="ScanDoc Auth Key")
    auth_key_validation_message = fields.Char(string="Auth Key Validation Message")
    is_auth_key_validated = fields.Boolean(
        string="Auth Key Validated", 
        compute="_compute_is_auth_key_validated",
        store=False
    )
    resume_scanner = fields.Boolean(string="Resume Scanner", default=False)
    vendorbill_receipt_scanner = fields.Boolean(
        string="Vendor Bill Scanner for Receipt"
    )
    vendorbill_scanner = fields.Boolean(string="Vendor Bill Scanner")

    scans_limit = fields.Char("Total Credits Purchased")
    used_credit = fields.Char("Used Credit")
    remaining_credit = fields.Char("Remaining Credit")
    transaction_ids = fields.One2many('transaction.history', 'company_id', string="Transaction Data")
    audit_history_ids = fields.One2many('audit.history','company_id', string="Audit Log Data")
    remaining_analysis_scan = fields.Integer(string="Analysis scan remaining")

    @api.depends('auth_key_validation_message')
    def _compute_is_auth_key_validated(self):
        """Compute if the authentication key is validated based on the validation message"""
        for record in self:
            record.is_auth_key_validated = (
                record.auth_key_validation_message == "Authentication key is valid."
            )
