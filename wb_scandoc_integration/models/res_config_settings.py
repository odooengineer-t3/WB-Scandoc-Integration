# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) Wan Buffer Services (<https://wanbuffer.com/>).
#
#    For Module Support : support@wanbuffer.com  or Call : +91 9638442270
#
##############################################################################
"""
This module extends `res.config.settings` to add configuration parameters
for integrating with the external ScanDoc service.

Main Features:
- Stores and validates ScanDoc Auth Key
- Toggles features like Resume, Vendor Bill, and Delivery Challan scanning
- Integrates with ir.config_parameter to persist settings
- Redirects to external auth key generation and validation endpoints
"""

import requests
from odoo import models, fields, _, api
from odoo.exceptions import ValidationError
from dateutil import parser
from datetime import timezone
import logging
from datetime import timezone
import pytz
from pytz import timezone
from datetime import datetime

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    """
    Adds ScanDoc integration configuration options to the Odoo settings screen.

    Features:
    - Manages auth key and scanner feature flags.
    - Provides an action to redirect to the external key generation page.
    - Verifies auth key via external API.
    - Controls access rights to resume scanning feature via groups.
    """

    _inherit = "res.config.settings"

    scandoc_auth_key = fields.Char(
        string="ScanDoc Auth Key", related="company_id.scandoc_auth_key", readonly=False
    )
    auth_key_validation_message = fields.Char(
        string="Auth Key Validation Message",
        related="company_id.auth_key_validation_message",
        readonly=False,
    )
    is_auth_key_validated = fields.Boolean(
        string="Auth Key Validated",
        related="company_id.is_auth_key_validated",
        readonly=True,
    )

    resume_scanner = fields.Boolean(
        string="Resume Scanner", related="company_id.resume_scanner", readonly=False
    )

    vendorbill_receipt_scanner = fields.Boolean(
        string="Vendor Bill Scanner for Receipt", related="company_id.vendorbill_receipt_scanner", readonly=False
    )

    vendorbill_scanner = fields.Boolean(
        string="Vendor Bill Scanner", related="company_id.vendorbill_scanner", readonly=False
    )
    scans_limit = fields.Char("Total Credits Purchased", related="company_id.scans_limit")
    used_credit = fields.Char("Used Credit", related="company_id.used_credit")
    remaining_credit = fields.Char("Remaining Credit", related="company_id.remaining_credit")
    transaction_ids = fields.One2many('transaction.history', 'company_id', string="Transaction Data")
    audit_history_ids = fields.One2many('audit.history','company_id', string="Audit Log Data")
    remaining_analysis_scan = fields.Integer(string="Analysis scan remaining", related="company_id.remaining_analysis_scan")

    def action_get_auth_key(self):
        """
        Redirects user to the external ScanDoc URL
         to obtain the authentication key.
        """
        return {
            "type": "ir.actions.act_url",
            "url": "https://portal.scandoc.xyz/login",
            "target": "blank",
        }

    def action_verify_auth_key(self):
        """
        Verify the ScanDoc authentication key using the ScanDoc API.
        Only valid keys will update company data and permissions.
        """

        if not self.scandoc_auth_key:
            raise ValidationError(_("Please enter an authentication key before verifying."))

        # Base API URLs
        validate_url = "https://scandocapi--scandoc-api.us-central1.hosted.app/api/documents/validate-auth"
        history_url = "https://scandocapi--scandoc-api.us-central1.hosted.app/api/history/scan"
        transaction_url = "https://scandocapi--scandoc-api.us-central1.hosted.app/api/billing/history"

        headers = {"Authorization": self.scandoc_auth_key}

        # ---- 1️⃣ Validate the key first ----
        try:
            response = requests.post(validate_url, json={"authKey": self.scandoc_auth_key}, timeout=10)
        except requests.exceptions.RequestException as e:
            raise ValidationError(_("Connection error during verification: %s") % str(e))

        if response.status_code != 200:
            raise ValidationError(_("Authentication key is invalid or unreachable."))

        resp_json = response.json()
        user_data = resp_json.get("user", {})
        analysis_scan_limit = user_data.get('analysisScansLimit')
        if not user_data:
            raise ValidationError(_("Invalid response from authentication server."))

        # ---- 2️⃣ If valid, update company data ----
        scans_used = user_data.get("scansUsed", 0)
        scans_limit = user_data.get("scansLimit", 0)
        remaining = max(scans_limit - scans_used, 0)
        company = self.company_id
        company.sudo().write({
            "scans_limit": scans_limit + scans_used,
            "used_credit": scans_used,
            "remaining_credit": scans_limit,
            "auth_key_validation_message": "Authentication key verified successfully.",
            "remaining_analysis_scan":analysis_scan_limit
        })

        # Save key globally
        self.env["ir.config_parameter"].sudo().set_param("wb_scandoc_integration.scandoc_auth_key", self.scandoc_auth_key)

        # ---- 3️⃣ Fetch transactions (optional) ----
        try:
            tx_resp = requests.get(transaction_url, headers=headers, timeout=10)

            if tx_resp.status_code == 200:
                tx_data = tx_resp.json().get("data", [])
                lines = []

                # Already stored invoice IDs
                existing = company.transaction_ids.mapped("invoice_name")

                for t in tx_data:
                    invoice_id = t.get("id") or "Unknown Invoice"
                    # Skip duplicates
                    if invoice_id in existing:
                        continue
                    # Parse purchaseDate safely
                    date_str = t.get("purchaseDate")
                    try:
                        # purchase_date = (
                        #     parser.parse(date_str)
                        #     .astimezone(timezone.utc)
                        #     .replace(tzinfo=None)
                        # )
                        dt_raw = parser.parse(date_str)  # API timestamp in UTC
                        ist_time = dt_raw.astimezone(timezone("Asia/Kolkata"))  # Convert to IST
                        purchase_date = ist_time.replace(tzinfo=None)
                    except Exception:
                        purchase_date = fields.Datetime.now()

                    # Calculate total → grandTotal > totalAmount > 0
                    total_amount = float(
                        t.get("grandTotal")
                        or t.get("totalAmount")
                        or 0
                    )

                    # Quantity → use scanCount > analysisScanCount > 0
                    quantity = (
                        t.get("scanCount")
                        or t.get("analysisScanCount")
                        or 0
                    )

                    # Add line
                    lines.append((0, 0, {
                        "invoice_name": invoice_id,                         # id
                        "quantity": quantity,                               # scanCount
                        "purchase_date_transaction": purchase_date,         # parsed datetime
                        "total": total_amount,                              # grandTotal / totalAmount
                        "status": t.get("status"),                          # Paid / Failed
                    }))

                # Write to Odoo
                if lines:
                    company.write({
                        "transaction_ids": [(5, 0, 0)] + lines
                    })
        except Exception as e:
            _logger.warning("Transaction fetch failed: %s", e)

        # ---- 4️⃣ Fetch history (optional) ----
        try:
            hist_resp = requests.get(history_url, headers=headers, timeout=20)
            if hist_resp.status_code == 200:
                data = hist_resp.json().get("data", [])
                lines = []
                for doc in data:
                    file_info = doc.get("fileInfo", {})
                    name = doc.get("fileName") 
                    processed = doc.get("createdAt")
                    doc_id = doc.get("id")
                    if processed:
                        dt_raw = parser.parse(processed)  # API timestamp in UTC
                        ist_time = dt_raw.astimezone(timezone("Asia/Kolkata"))  # Convert to IST
                        processed_date = ist_time.replace(tzinfo=None)
                        # processed_date = parser.parse(processed).astimezone(timezone.utc).replace(tzinfo=None)
                        lines.append((0, 0, {
                            "document_id": doc_id,
                            "document_name": name,
                            "status": "Success" if doc.get('status') == 'Success' else "Failed",
                            "auditlog_date": processed_date,
                        }))
                if lines:
                    company.write({"audit_history_ids": [(5, 0, 0)] + lines})
        except Exception as e:
            _logger.warning("History fetch failed: %s", e)

        # ---- 5️⃣ Grant access & commit ----
        self._grant_scandoc_access()
        # self.env.cr.commit()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Authentication Key Verified"),
                "message": _("The key has been successfully validated."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_reset_auth_key(self):
        """
        Reset the authentication key and validation status
        """
        # Clear the authentication key and validation message on the company
        self.company_id.write({
            'scandoc_auth_key': False,
            'auth_key_validation_message': False,
        })
        
        # Clear from system parameters
        self.env["ir.config_parameter"].sudo().set_param(
            "wb_scandoc_integration.scandoc_auth_key", ""
        )
        
        # Revoke access to ScanDoc authenticated group
        self._revoke_scandoc_access()
        
        # Trigger a refresh of the form view to show the changes
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def _grant_scandoc_access(self):
        """
        Grant access to ScanDoc features by adding all active users to the authenticated group
        and all feature-specific groups
        """
        try:
            # Get all ScanDoc groups
            scandoc_group = self.env.ref('wb_scandoc_integration.group_scandoc_authenticated')
            po_scanner_group = self.env.ref('wb_scandoc_integration.group_po_scanner')
            resume_scanner_group = self.env.ref('wb_scandoc_integration.group_resume_scanner')
            receipt_scanner_group = self.env.ref('wb_scandoc_integration.group_receipt_scanner')
            
            all_groups = [scandoc_group, po_scanner_group, resume_scanner_group, receipt_scanner_group]
            
            # Get all active users with login access
            active_users = self.env['res.users'].sudo().search([
                ('active', '=', True),
                ('share', '=', False)  # Exclude portal users
            ])
            
            # Add all active users to all ScanDoc groups
            for group in all_groups:
                group.sudo().write({
                    'users': [(4, user.id) for user in active_users]
                })
            
            # Also ensure admin user is in all groups
            admin_user = self.env.ref('base.user_admin')
            for group in all_groups:
                if admin_user not in group.users:
                    group.sudo().write({
                        'users': [(4, admin_user.id)]
                    })
                
        except Exception as e:
            # Log error but don't break the validation process
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error("Failed to grant ScanDoc access: %s", str(e))

    def _revoke_scandoc_access(self):
        """
        Revoke access to ScanDoc features by removing all users from the authenticated group
        and all feature-specific groups
        """
        try:
            # Get all ScanDoc groups
            scandoc_group = self.env.ref('wb_scandoc_integration.group_scandoc_authenticated')
            po_scanner_group = self.env.ref('wb_scandoc_integration.group_po_scanner')
            resume_scanner_group = self.env.ref('wb_scandoc_integration.group_resume_scanner')
            receipt_scanner_group = self.env.ref('wb_scandoc_integration.group_receipt_scanner')
            
            all_groups = [scandoc_group, po_scanner_group, resume_scanner_group, receipt_scanner_group]
            
            # Remove all users from all ScanDoc groups
            for group in all_groups:
                group.sudo().write({
                    'users': [(5, 0, 0)]  # Remove all users
                })
            
        except Exception as e:
            # Log error but don't break the process
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error("Failed to revoke ScanDoc access: %s", str(e))

    @api.model
    def _check_and_grant_initial_access(self):
        """
        Check if there's already a valid auth key and grant access accordingly.
        This is called during module installation/upgrade.
        """
        try:
            # Check if auth key is configured and validated
            company = self.env.company
            if company.is_auth_key_validated:
                # Grant access to authenticated group
                self._grant_scandoc_access()
        except Exception as e:
            # Log error but don't break installation
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error("Failed to check initial ScanDoc access: %s", str(e))

    def set_values(self):
        super().set_values()
        ICP = self.env["ir.config_parameter"].sudo()

        toggle_config = {
            "resume_scanner": (
                "wb_scandoc_integration.resume_scanner",
                "wb_scandoc_integration.group_resume_scanner",
            ),
            "vendorbill_receipt_scanner": (
                "wb_scandoc_integration.vendorbill_receipt_scanner",
                "wb_scandoc_integration.group_receipt_scanner",
            ),
            "vendorbill_scanner": (
                "wb_scandoc_integration.vendorbill_scanner",
                "wb_scandoc_integration.group_po_scanner",
            ),
        }

        for field, (param_key, group_xmlid) in toggle_config.items():
            value = getattr(self, field)
            ICP.set_param(param_key, str(value))
            group = self.env.ref(group_xmlid, raise_if_not_found=False)
            if not group:
                continue

            users = self.env["res.users"].search([("company_id", "=", self.env.company.id)])

            if value:
                users.write({"groups_id": [(4, group.id)]})
            else:
                users.write({"groups_id": [(3, group.id)]})

        # ------------------------------------------------------------
        # 🔥 MAIN FIX: enable Quick Scan menu when ANY boolean is true
        # ------------------------------------------------------------

        enable_quick_scan = (
            self.resume_scanner
            or self.vendorbill_receipt_scanner
            or self.vendorbill_scanner
        )

        quick_scan_group = self.env.ref("wb_scandoc_integration.group_scandoc_authenticated")

        users = self.env["res.users"].search([("company_id", "=", self.env.company.id)])

        if enable_quick_scan:
            users.write({"groups_id": [(4, quick_scan_group.id)]})
        else:
            users.write({"groups_id": [(3, quick_scan_group.id)]})

    @api.model
    def get_values(self):
        """
        Override getter to retrieve stored config values
        from ir.config_parameter.
        """
        res = super().get_values()
        ICP = self.env["ir.config_parameter"].sudo()

        toggle_config = {
            "resume_scanner": "wb_scandoc_integration.resume_scanner",
            "vendorbill_receipt_scanner": "wb_scandoc_integration.vendorbill_receipt_scanner",
            "vendorbill_scanner": "wb_scandoc_integration.vendorbill_scanner",
        }

        for field, param_key in toggle_config.items():
            res[field] = ICP.get_param(param_key, "False") == "True"

        return res