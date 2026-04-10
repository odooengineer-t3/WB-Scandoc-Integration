# -*- coding: utf-8 -*-
from odoo import models, fields , api, _
import requests
import base64
from odoo.exceptions import UserError, ValidationError

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"
    
    
    def action_parse_vendor_bill(self):
        pass
        # """
        # Button action to open the scandoc wizard.
        # Used to parse CV and fill in related fields automatically.
        # """
        # action = self.env["ir.actions.act_window"]._for_xml_id(
        #     "wb_scandoc_purchase.action_scandoc_po_wizard"
        # )
        # return action


class CrmLead(models.Model):
    _inherit = "crm.lead"

    lead_code = fields.Char(string="Lead Code", readonly=True, copy=False)
    user_vistors_id = fields.Char(string="Doc ID")
    doc_id = fields.Char(string="Doc ID")
    lead_sync_status = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ], default='pending')

    sync_error = fields.Char()

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence'].sudo().search([
            ('code', '=', 'crm.lead')
        ], limit=1)
        for vals in vals_list:
            if not vals.get("lead_code"):
                vals["lead_code"] = self.env['ir.sequence'].next_by_code('crm.lead') or 'New'
        return super().create(vals_list)

    def _cron_create_lead_visiting_card(self):
        company = self.env.company

        if not company.scandoc_auth_key:
            raise ValidationError("Missing auth key user not logged in.")

        url = (
            "https://scandocapi--scandoc-api.us-central1.hosted.app/api/"
            "history/document-data?page=1&pageSize=10&document_type=Visiting Card"
        )

        try:
            response = requests.get(url, headers={"Authorization": company.scandoc_auth_key}, timeout=10)
        except Exception as e:
            raise ValidationError(f"API unreachable: {e}")

        if response.status_code != 200:
            raise ValidationError("Invalid key or unreachable API")

        records = response.json().get("data", [])
        Lead = self.env["crm.lead"]
        Partner = self.env["res.partner"].sudo()
        Attachment = self.env["ir.attachment"].sudo()

        for rec in records:

            doc_id = rec.get("docId")
            # --------------------------------------------
            # 🔥 1️⃣ SKIP if doc_id already exists
            # --------------------------------------------
            existing_lead = Lead.search([("doc_id", "=", doc_id)], limit=1)
            if existing_lead:
                continue  # <-- DO NOT CRE

            # --------------------------------------------
            # 1️⃣ Extract fields from BOTH response formats
            # --------------------------------------------
            if "data" in rec.get("response", {}):
                extracted = rec["response"]["data"]
            else:
                extracted = rec.get("response", {})

            personal = extracted.get("personal_details", {}) or {}
            contact = extracted.get("contact_information", {}) or {}
            company_det = extracted.get("company_details", {}) or {}
            address = extracted.get("address", {}) or {}

            full_name = personal.get("full_name")
            email = contact.get("email_address")
            phone = contact.get("mobile_number")
            website = contact.get("website")

            # --------------------------------------------
            # 2️⃣ Safe partner name (fixes SQL constraint)
            # --------------------------------------------
            partner_name = (
                full_name
                or company_det.get("company_name")
                or email
                or phone
                or "Unknown Partner"
            )

            # --------------------------------------------
            # 3️⃣ Partner search domain
            # --------------------------------------------
            domain = []
            if email:
                domain = [("email", "=", email)]
            elif phone:
                domain = [("phone", "=", phone)]
            else:
                domain = [("name", "=", partner_name)]

            partner = Partner.search(domain, limit=1)

            # --------------------------------------------
            # 4️⃣ Create partner safely
            # --------------------------------------------
            if not partner:
                partner = Partner.create({
                    "name": partner_name,
                    "email": email,
                    "phone": phone,
                    "street": address.get("office_address"),
                    "website": website,
                })

            # --------------------------------------------
            # 5️⃣ Create Lead
            # --------------------------------------------
            lead = Lead.create({
                "name": full_name or "Visiting Card Lead",
                "contact_name": full_name,
                "email_from": email,
                "phone": phone,
                "function": personal.get("job_title"),
                "partner_id": partner.id,
                "doc_id": rec.get("docId"),
            })

            # --------------------------------------------
            # 6️⃣ Handle files (supports all formats)
            # --------------------------------------------
            file_info = (
                rec.get("fileInfo")
                or rec.get("response", {}).get("file_info")
                or extracted.get("file_info")
            )

            file_url = None
            if file_info:
                file_url = file_info.get("url")

            if file_url:
                try:
                    img_resp = requests.get(file_url)
                    if img_resp.status_code == 200:
                        attachment = Attachment.create({
                            "name": file_info.get("originalName", "file"),
                            "res_model": "crm.lead",
                            "res_id": lead.id,
                            "type": "binary",
                            "datas": base64.b64encode(img_resp.content),
                        })

                        lead.message_post(
                            body="Visiting card uploaded",
                            attachment_ids=[attachment.id],
                        )
                except Exception:
                    lead.write({
                        "lead_sync_status": "failed",
                        "sync_error": "Attachment failed"
                    })
                    continue

            # --------------------------------------------
            # 7️⃣ Lead status
            # --------------------------------------------
            lead.write({
                "lead_sync_status": "success",
                "sync_error": False
            })