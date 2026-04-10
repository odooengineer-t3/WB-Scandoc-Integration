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
Production-ready ScanDoc Integration Module

This module provides enterprise-grade document processing capabilities with:
- Comprehensive error handling and logging
- Input validation and security checks  
- Robust currency detection and activation
- Graceful failure recovery
- Performance optimizations

Author: Wan Buffer Services
License: OPL-1
Version: 18.0.1.0.0
"""
import re
import io
import json
import base64
import logging
import mimetypes
from dateutil.relativedelta import relativedelta
import pytz
from dateutil import parser
from pytz import timezone
from datetime import datetime

try:
    import openpyxl
except ImportError:
    openpyxl = None
    
try:
    import requests
except ImportError:
    requests = None
    
try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from PIL import Image, ImageOps, ImageFilter, ImageEnhance
except ImportError:
    Image = ImageOps = ImageFilter = ImageEnhance = None

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError, AccessError

_logger = logging.getLogger(__name__)

# Production constants
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.docx', '.xlsx']
ALLOWED_MIME_TYPES = [
    'application/pdf',
    'image/png', 'image/jpeg', 'image/tiff', 'image/bmp',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
]

_logger = logging.getLogger(__name__)


class ResumeParserWizard(models.TransientModel):
    """
    Production-ready wizard for document processing with comprehensive error handling,
    input validation, and security features.
    """
    _name = 'resume.parser.wizard'
    _description = 'Resume Parser Wizard - Production Ready'

    file = fields.Binary("File", required=True)
    file_name = fields.Char("Filename", required=True)
    file_scanned = fields.Boolean(string="File Scanned?")
    doc_type = fields.Selection(selection="_get_doc_type_selection", string="Document Type")
    doc_type_readonly = fields.Boolean(string="Readonly Doc Type",
                                       compute="_compute_doc_type_readonly",
                                       store=True)
    
    # Company validation fields
    company_mismatch_detected = fields.Boolean(
        string="Company Mismatch Detected", 
        default=False,
        help="Indicates if the invoice is addressed to a different company"
    )
    external_invoice_details = fields.Text(
        string="External Invoice Details",
        help="Details about the company mismatch for user review"
    )
    confirm_external_processing = fields.Boolean(
        string="Confirm External Invoice Processing",
        default=False,
        help="User confirmation to process invoice for external company"
    )
    
    # Data storage fields to avoid re-calling API
    extracted_data_json = fields.Text(
        string="Extracted Data (JSON)",
        help="Stores extracted data from ScanDoc API to avoid re-processing"
    )
    data_extraction_completed = fields.Boolean(
        string="Data Extraction Completed",
        default=False,
        help="Indicates if data has already been extracted from API"
    )
    api_call_timestamp = fields.Datetime(
        string="API Call Timestamp",
        help="When the API was last called for this file"
    )
    
    @api.model
    def _get_doc_type_selection(self):
        """
        Returns dynamic selection list for document types based on configuration settings.
        Only shows document types that are enabled in the configuration.
        """
        selection = []
        
        # Get configuration parameters
        ICP = self.env["ir.config_parameter"].sudo()
        
        # Check each scanner type and add to selection if enabled
        if ICP.get_param("wb_scandoc_integration.resume_scanner", "False") == "True":
            selection.append(('Resume', 'Resume'))
        
        if ICP.get_param("wb_scandoc_integration.vendorbill_scanner", "False") == "True":
            selection.append(('VendorBill', 'Vendor Bill'))
            
        if ICP.get_param("wb_scandoc_integration.vendorbill_receipt_scanner", "False") == "True":
            selection.append(('DeliveryChalaan', 'Delivery Challan'))
        
        return selection
    
    @api.onchange('file', 'file_name')
    def _onchange_file(self):
        """Clear stored data when a new file is uploaded"""
        if self.file and self.data_extraction_completed:
            self._clear_extracted_data()
            # Also reset company validation flags
            self.company_mismatch_detected = False
            self.external_invoice_details = False
            self.confirm_external_processing = False

    @api.onchange('confirm_external_processing')
    def _onchange_confirm_external_processing(self):
        """Handle confirmation checkbox changes"""
        if self.confirm_external_processing and self.company_mismatch_detected:
            # 🔧 FIX: Ensure the confirmation state is saved immediately
            try:
                self.sudo()._write({'confirm_external_processing': True})
            except Exception as e:
                _logger.warning("⚠️ Could not save confirmation state: %s", str(e))
        elif not self.confirm_external_processing and self.company_mismatch_detected:
            try:
                self.sudo()._write({'confirm_external_processing': False})
            except Exception as e:
                _logger.warning("⚠️ Could not save confirmation state: %s", str(e))

    def _clear_extracted_data(self):
        """Clear stored extracted data when needed"""
        self.write({
            'extracted_data_json': False,
            'data_extraction_completed': False,
            'api_call_timestamp': False,
        })

    def _store_extracted_data(self, data):
        """Store extracted data to avoid re-calling API"""
        try:

            data_json = json.dumps(data, default=str, ensure_ascii=False)
            self.write({
                'extracted_data_json': data_json,
                'data_extraction_completed': True,
                'api_call_timestamp': fields.Datetime.now(),
            })
        except Exception as e:
            _logger.error("❌ Failed to store extracted data: %s", str(e))

    def _get_stored_data(self):
        """Retrieve stored extracted data if available"""
        
        if self.data_extraction_completed and self.extracted_data_json:
            try:
                data = json.loads(self.extracted_data_json)
                return data
            except Exception as e:
                _logger.error("❌ Failed to parse stored data: %s", str(e))
                self._clear_extracted_data()
        return None

    @api.depends('doc_type')
    def _compute_doc_type_readonly(self):
        for record in self:
            record.doc_type_readonly = self.env.context.get('readonly_doc_type', False)

    # ===========================================
    # PRODUCTION SECURITY & VALIDATION METHODS
    # ===========================================
    
    def _check_dependencies(self):
        """Check if all required Python packages are available"""
        missing_deps = []
        
        if requests is None:
            missing_deps.append('requests')
        if openpyxl is None:
            missing_deps.append('openpyxl')
        if pytesseract is None:
            missing_deps.append('pytesseract')
        if PdfReader is None:
            missing_deps.append('PyPDF2')
        if Image is None:
            missing_deps.append('Pillow')
            
        if missing_deps:
            raise UserError(_(
                "Missing required Python packages: %s\n"
                "Please install them using: pip install %s"
            ) % (', '.join(missing_deps), ' '.join(missing_deps)))
    
    def _validate_file_security(self):
        """Comprehensive file validation for security and compatibility"""
        if not self.file or not self.file_name:
            raise ValidationError(_("File and filename are required"))
            
        # Check file size
        file_data = base64.b64decode(self.file)
        if len(file_data) > MAX_FILE_SIZE:
            raise ValidationError(_(
                "File size exceeds maximum limit of %sMB"
            ) % (MAX_FILE_SIZE // (1024 * 1024)))
        
        # Check file extension
        extension = self._get_file_extension(self.file_name)
        if extension not in ALLOWED_EXTENSIONS:
            raise ValidationError(_(
                "File type '%s' not allowed. Supported formats: %s"
            ) % (extension, ', '.join(ALLOWED_EXTENSIONS)))
        
        # Check MIME type
        mime_type, _ = mimetypes.guess_type(self.file_name)
        if mime_type and mime_type not in ALLOWED_MIME_TYPES:
            raise ValidationError(_(
                "MIME type '%s' not allowed for security reasons"
            ) % mime_type)
            
        # Basic malware check - scan for suspicious patterns
        try:
            # Check for suspicious file headers/magic bytes
            if file_data.startswith(b'MZ') and extension not in ['.exe', '.dll']:
                raise ValidationError(_("Suspicious file detected - executable content in non-executable file"))
                
            # Check for embedded scripts in PDF
            if extension == '.pdf' and b'/JavaScript' in file_data:
                _logger.warning("PDF with JavaScript detected: %s", self.file_name)
                
        except Exception as e:
            _logger.error("File validation error: %s", str(e))
            raise ValidationError(_("File validation failed: %s") % str(e))
    
    def _get_safe_filename(self):
        """Sanitize filename for safe processing"""
        if not self.file_name:
            return "unknown_file"
            
        # Remove path separators and dangerous characters
        safe_name = re.sub(r'[^\w\-_\.]', '_', self.file_name)
        # Ensure it's not too long
        if len(safe_name) > 255:
            name_part = safe_name[:240]
            extension = self._get_file_extension(safe_name)
            safe_name = name_part + extension
            
        return safe_name
    
    def _log_processing_start(self):
        """Log the start of document processing for audit trail"""
        pass

    def _get_file_extension(self, filename):
        """
        Extracts the file extension from a filename.

        :param filename: The name of the file.
        :return: File extension with a leading dot (e.g., '.pdf').
        """
        return '.' + filename.split('.')[-1].lower() if '.' in filename else ''

    def generate_sentiment_visual(self, sentiment_score):
        """
        Generate an emoji and label representation for a given sentiment score.

        :param sentiment_score: The sentiment score as an integer.
        :return: A string with visual (emoji) feedback.
        """

        result = ""
        if 70 <= sentiment_score <= 100:
            result = "🟢 (Positive) - Great Fit!"
        elif 60 <= sentiment_score <= 69:
            result = "🟡 (Neutral) - Potential Fit"
        elif 0 <= sentiment_score < 60:
            result = "🔴 (Negative) - Weak Fit"
        else:
            result = "⚪ (Invalid Score)"
        return result

    def process_resume(self):
        self = self.sudo()
        self.ensure_one()

        # ------------------------------------------------------------------
        # 1. Get Auth Key
        # ------------------------------------------------------------------
        auth_key = self.env['ir.config_parameter'].sudo().get_param(
            'wb_scandoc_integration.scandoc_auth_key'
        )
        if not auth_key:
            raise UserError("Please login to ScanDoc first.")

        if not self.file or not self.file_name:
            raise UserError(_("Please upload a valid file."))

        # ------------------------------------------------------------------
        # 2. Decode & Validate File
        # ------------------------------------------------------------------
        try:
            file_content = base64.b64decode(self.file)
        except Exception as e:
            raise UserError(_("Error decoding file: %s") % str(e))

        mimetype, _ = mimetypes.guess_type(self.file_name)
        mimetype = mimetype or "application/octet-stream"
        allowed = [
            "application/pdf", "image/jpeg", "image/png",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ]
        if mimetype not in allowed:
            raise UserError(_("Unsupported file type: %s") % mimetype)

        # ------------------------------------------------------------------
        # 3. Call ScanDoc Extract API
        # ------------------------------------------------------------------
        url = "https://scandocapi--scandoc-api.us-central1.hosted.app/external-extract"
        try:
            response = requests.post(
                url,
                data={'authKey': auth_key, 'doc_type': self.doc_type.lower()},
                files=[('file', (self.file_name, file_content, mimetype))],
                timeout=30
            )
            parsed_data = response.json()
            if parsed_data.get("error"):
                raise ValidationError(parsed_data.get("error"))

            user_data = parsed_data.get("user", {})
            remaining_scans = user_data.get("remainingScans")
            if not remaining_scans or remaining_scans <= 0:
                raise ValidationError(_("You have exceeded your ScanDoc credit limit."))

            # Update legacy config param
            self.env["ir.config_parameter"].sudo().set_param(
                "wb_scandoc_integration.scandoc_credit", remaining_scans
            )

        except requests.exceptions.RequestException as e:
            raise UserError(f"ScanDoc API failed: {e}")

        # ------------------------------------------------------------------
        # 4. UPDATE CREDITS ON COMPANY
        # ------------------------------------------------------------------
        company = self.env.company
        scans_limit = int(company.scans_limit or 0)
        used_credits = scans_limit - remaining_scans
        company.sudo().write({
            'remaining_credit': remaining_scans,
            'used_credit': used_credits,
        })
        self.file_scanned = True

        # ------------------------------------------------------------------
        # 5. FETCH & SYNC AUDIT HISTORY & BILLING HISTORY
        # ------------------------------------------------------------------
        headers = {"Authorization": auth_key}
        company = self.env.company

        # ---- Audit History ----
        try:
            hist_resp = requests.get(
                "https://scandocapi--scandoc-api.us-central1.hosted.app/api/history/scan?document_type=resume",
                headers=headers, timeout=10
            )
            print("\n history-----------", hist_resp)
            if hist_resp.status_code == 200:
                data = hist_resp.json().get("data", [])
                print("\n data----------", data)
                history_lines = []
                for doc in data:
                    doc_id = doc.get("id")
                    name = doc.get("fileName") or "Unknown"
                    status = "Success" if doc.get("status") == "Success" else "Failed"
                    dt = fields.Datetime.now()
                    if doc.get("createdAt"):
                        if doc.get("createdAt"):
                            try:
                                # Parse the original UTC timestamp
                                dt_raw = parser.parse(doc["createdAt"])

                                # Convert to IST (Asia/Kolkata)
                                ist_tz = timezone("Asia/Kolkata")
                                dt_ist = dt_raw.astimezone(ist_tz)

                                # Remove tzinfo (Odoo stores naive datetime in server time)
                                dt = dt_ist.replace(tzinfo=None)
                            except Exception as e:
                                print("Parse error:", e)
                    history_lines.append((0, 0, {
                        "document_name": name,
                        "status": status,
                        "auditlog_date": dt,
                        "document_id":doc_id,
                    }))
                if history_lines:
                    company.write({"audit_history_ids": [(5, 0, 0)] + history_lines})
        except Exception as e:
            print("Warning: History fetch failed:", e)

        # ---- Billing Transactions ----
        try:
            tx_resp = requests.get(
                "https://scandocapi--scandoc-api.us-central1.hosted.app/api/billing/history",
                headers=headers, timeout=10
            )
            if tx_resp.status_code == 200:
                tx_data = tx_resp.json().get("data", [])
                tx_lines = []
                existing = company.transaction_ids.mapped("invoice_name")
                for t in tx_data:
                    inv = t.get("invoiceNumber") or t.get("id") or "Unknown"
                    if inv in existing:
                        continue
                    dt = fields.Datetime.now()
                    if t.get("purchaseDate"):
                        try:
                            dt = parser.parse(t["purchaseDate"]).astimezone(timezone.utc).replace(tzinfo=None)
                        except:
                            pass
                    tx_lines.append((0, 0, {
                        "invoice_name": inv,
                        "quantity": str(t.get("quantity", 0)),
                        "purchase_date_transaction": dt,
                        "total": float(t.get("total", 0)),
                        "status": t.get("status", "completed"),
                    }))
                if tx_lines:
                    company.write({"transaction_ids": [(5, 0, 0)] + tx_lines})
        except Exception as e:
            print("Warning: Transaction fetch failed:", e)

        # ------------------------------------------------------------------
        # 6. PROCESS RESUME DATA (Your Logic)
        # ------------------------------------------------------------------
        candidate_vals, application_vals, partner_vals = {}, {}, {}
        current_company_id = self.env.company.id
        candidate_vals["company_id"] = current_company_id
        application_vals["company_id"] = current_company_id

        extracted = parsed_data.get("extractedData", {}).get("data", {})
        job_position = (extracted.get("personal_information", {}).get("job_profile")or (extracted.get("work_experience", [{}])[0].get("position")))
        job_record = None
        job_rec = self.env["hr.job"].sudo()
        if job_position:
            # 1️⃣ Search existing job position
            job_record = job_rec.search([("name", "=", job_position)], limit=1)

            # 2️⃣ If job not found → create new
            if not job_record:
                job_record = job_rec.create({
                    "name": job_position,
                })
        application_vals["job_id"] = job_record.id
        # --- Validate extracted data ---
        if extracted:
            application_vals["sentiment_json_data"] = json.dumps(extracted)
            application_vals["sentiment_data"] = extracted

        # Personal Info
        personal_info = extracted.get("personal_information", {})
        if personal_info.get("full_name"):
            partner_vals.update({"type": "contact", "name": personal_info["full_name"]})
            candidate_vals["partner_name"] = application_vals["partner_name"] = personal_info["full_name"]
        if personal_info.get("email"):
            partner_vals["email"] = candidate_vals["email_from"] = application_vals["email_from"] = personal_info["email"]
        if personal_info.get("phone"):
            partner_vals["phone"] = candidate_vals["partner_phone"] = application_vals["partner_phone"] = personal_info["phone"]
        if personal_info.get("linkedin_profile"):
            linkedin_url = personal_info["linkedin_profile"].strip()

            # Normalize LinkedIn link
            if not linkedin_url.startswith("http"):
                # User just gave handle or partial path
                if "linkedin.com" not in linkedin_url:
                    linkedin_url = f"https://www.linkedin.com/in/{linkedin_url.lstrip('/')}"
                else:
                    linkedin_url = f"https://{linkedin_url.lstrip('/')}"
            elif "linkedin.com/in" not in linkedin_url:
                # Example: "https://linkedin.com/john-doe"
                linkedin_url = linkedin_url.replace("linkedin.com", "linkedin.com/in")
            candidate_vals["linkedin_profile"] = application_vals["linkedin_profile"] = linkedin_url

        # Skills
        skills = extracted.get("skills", {})
        if skills:
            candidate_vals["applicant_skill_ids"] = application_vals["applicant_skill_ids"] = self._process_skills(skills)

        # Work Experience
        work_experience = extracted.get("work_experience", [])
        if work_experience:
            total_months = 0
            work_experience_lines = []
            for exp in work_experience:
                start_date = exp.get("start_date") or ""
                end_date = exp.get("end_date") or ""
                duration_str = exp.get("duration_human") or ""
                months = int(exp.get("duration_months") or 0)
                total_months += months
                if not duration_str and months:
                    years, rem_months = divmod(months, 12)
                    duration_str = f"{years} years {rem_months} months" if years and rem_months else f"{years} years" if years else f"{rem_months} months"
                work_experience_lines.append((0, 0, {
                    "company_name": exp.get("company") or "Unknown Company",
                    "role": exp.get("position") or "",
                    "start_date": start_date,
                    "end_date": end_date or "Present",
                    "duration": duration_str,
                }))
            application_vals["work_experience_ids"] = work_experience_lines
            if total_months:
                years, months = divmod(total_months, 12)
                total_display = f"{years} years {months} months" if years and months else f"{years} years" if years else f"{months} months"
                application_vals["total_work_experience"] = total_display

        # Education
        education = extracted.get("education", [])
        if education:
            application_vals["education_ids"] = [
                (0, 0, {
                    "degree": edu.get("degree") or "",
                    "institution": edu.get("institution") or "",
                    "degree_duration": f"{edu.get('start_date') or ''} - {edu.get('end_date') or ''}",
                }) for edu in education
            ]

        # Professional Summary
        summary = extracted.get("professional_summary", {})
        if summary.get("summary_text"):
            application_vals["applicant_notes"] = summary.get("summary_text")

        if not partner_vals:
            raise UserError("Please upload a valid resume")

        # Create/Update Partner
        partner = self.env["res.partner"].sudo().search([
            ("name", "=", partner_vals.get("name")),
            "|", ("email", "=", partner_vals.get("email") or ""),
            ("phone", "=", partner_vals.get("phone") or "")
        ], limit=1)
        partner = partner or self.env["res.partner"].sudo().create(partner_vals)
        partner.write(partner_vals)

        # Create/Update Candidate
        candidate = self.env["hr.applicant"].sudo().search([
            ("partner_id", "=", partner.id)
        ], order="id desc", limit=1)
        if not candidate:
            candidate = self.env["hr.applicant"].sudo().create(candidate_vals)
        else:
            # candidate.skill_ids.unlink() # Not needed if using (5,0,0) in commands
            candidate.write(candidate_vals)

        # Create/Update Applicant
        application_vals["candidate_id"] = candidate.id
        application_vals["stage_id"] = self.env.ref('hr_recruitment.stage_job0').id
        application = self.env["hr.applicant"].sudo().browse(self.env.context.get("active_id"))
        if application:
            application.sudo().write(application_vals)
        else:
            application = self.env["hr.applicant"].sudo().create(application_vals)

        # Attach File
        self.env["ir.attachment"].sudo().create({
            "name": self.file_name,
            "res_model": "hr.applicant",
            "res_id": application.sudo().id,
            "type": "binary",
            "datas": self.file,
            "mimetype": mimetype,
        })

        # ------------------------------------------------------------------
        # 7. RETURN → REFRESH UI
        # ------------------------------------------------------------------
        if not self.env.context.get("active_id"):
            return {
                "type": "ir.actions.act_window",
                "res_model": "hr.applicant",
                "res_id": application.sudo().id,
                "view_mode": "form",
                "target": "current",
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'refresh_credits',
        }

    def _process_skills(self, skills_dict):
        """
        Process skills and return commands for applicant_skill_ids One2many field.
        """
        skill_commands = [(5, 0, 0)]
        
        # Cache for skill levels to avoid repetitive searches
        default_levels = {} 

        def _nice_category(raw):
            s = re.sub(r'_+', ' ', raw).strip()
            return s.title()
            
        # Get a default level (e.g., 'Beginner' or first available)
        def _get_default_level(skill_type_id, skill_name=""):
            if skill_type_id in default_levels:
                return default_levels[skill_type_id]
            
            # Try to find Beginner
            level = self.env['hr.skill.level'].sudo().search([
                ('skill_type_id', '=', skill_type_id),
                ('name', 'ilike', 'Beginner')
            ], limit=1)
            
            # If no Beginner, try ANY level
            if not level:
                level = self.env['hr.skill.level'].sudo().search([
                    ('skill_type_id', '=', skill_type_id)
                ], order='level_progress asc', limit=1)
            
            # If STILL no levels, create defaults
            if not level:
                # Create standard levels for this new type
                self.env['hr.skill.level'].sudo().create([
                    {'name': 'Beginner', 'skill_type_id': skill_type_id, 'level_progress': 0},
                    {'name': 'Intermediate', 'skill_type_id': skill_type_id, 'level_progress': 50},
                    {'name': 'Expert', 'skill_type_id': skill_type_id, 'level_progress': 100},
                ])
                # Search again for Beginner
                level = self.env['hr.skill.level'].sudo().search([
                    ('skill_type_id', '=', skill_type_id),
                    ('name', '=', 'Beginner')
                ], limit=1)
                
            if level:
                default_levels[skill_type_id] = level.id
                return level.id
            return False

        for raw_category, skill_names in skills_dict.items():
            nice_category = _nice_category(raw_category)

            # Find or create skill type
            skill_type = self.env['hr.skill.type'].sudo().search([
                ('name', 'ilike', nice_category)
            ], limit=1)

            if skill_type:
                clean_name = skill_type.name.strip()
                if clean_name != skill_type.name:
                    skill_type.write({'name': clean_name})
                if clean_name.title() != skill_type.name:
                    skill_type.write({'name': clean_name.title()})

            if not skill_type:
                skill_type = self.env['hr.skill.type'].sudo().create({
                    'name': nice_category,
                })

            # Process each skill in the category
            for skill_name in skill_names:
                if not skill_name:
                    continue
                    
                skill_name_clean = skill_name.strip()
                
                # Find or create the skill
                skill = self.env['hr.skill'].sudo().search([
                    ('name', '=', skill_name_clean),
                    ('skill_type_id', '=', skill_type.id),
                ], limit=1)

                if not skill:
                    skill = self.env['hr.skill'].sudo().create({
                        'name': skill_name_clean,
                        'skill_type_id': skill_type.id,
                    })

                # Prepare One2many command for hr.applicant.skill
                level_id = _get_default_level(skill_type.id)
                if level_id:
                     skill_commands.append((0, 0, {
                        'skill_id': skill.id,
                        'skill_type_id': skill_type.id,
                        'skill_level_id': level_id,
                     }))

        return skill_commands

    def _build_sentiment_html(self, score, sentiment_data, tone_data):
        """
        Builds a styled HTML block for visualizing sentiment and tone data.

        :param score: Overall sentiment score as integer.
        :param sentiment_data: Dictionary of sentiment scores and justifications.
        :param tone_data: Dictionary of tone interpretations and keyword counts.
        :return: HTML string to be rendered in the applicant form.
        """
        visual = self.generate_sentiment_visual(score)
        stability = sentiment_data.get("Work Stability Check", {})

        html = f"""
               <div style="max-width: 600px; margin: auto; background: rgba(0,0,0,0.05);
                           padding: 24px; border-radius: 16px;
                           box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                   <!-- Section Header -->
                   <h2 style="margin-top: 0; font-size: 24px; color: #222;">Sentiment Analysis</h2>

                   <!-- Sentiment Block -->
                   <div style="border: 1px solid #eee; border-radius: 12px; padding: 16px;
                               margin-bottom: 24px; box-shadow: 0 6px 20px rgba(0, 0, 0, 0.30);
                               background-color: #f9f9f9;">
                       <p style="margin: 0; font-size: 16px;">
                           <span style="font-size: 20px;">🎯 
                               <strong>Sentiment Analysis</strong>
                           </span>
                       </p>
                       <p style="margin: 4px 0;"><strong>Overall Sentiment:</strong> {visual}</p>
                       <p style="margin: 4px 0;"><strong>Polarity Score:</strong> {score}%</p>
                       <p style="margin: 4px 0;"><strong>Subjectivity Score:</strong>
                           {sentiment_data.get('Subjectivity Score')}
                       </p>
                       <p style="margin: 4px 0;"><strong>Justification:</strong>
                           {sentiment_data.get('Justification')}
                       </p>
                   </div>

                   <!-- Work Stability -->
                   <div style="background: #fff1f0; border-left: 5px solid #ff4d4f;
                               border-radius: 12px; padding: 16px; margin-bottom: 24px;
                               box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
                               transition: box-shadow 0.3s ease;">
                       <p style="margin: 0; font-size: 16px;">
                           <span style="font-size: 18px;">🔴</span>
                           <strong>Work Stability Check</strong>
                       </p>
                       <p style="margin: 6px 0;"><strong>Risk Level:</strong>
                           {stability.get('Risk Level')}
                       </p>
                       <p style="margin: 6px 0;"><strong>Job Changes in Last 6 Months:</strong>
                           {stability.get('Job Changes in Last 6 Months')}
                       </p>
                       <p style="margin: 6px 0;"><strong>Job Changes in Last 1 Year:</strong> 
                           {stability.get('Job Changes in Last 1 Year')}
                       </p>
                       <p style="margin: 6px 0;"><strong>Average Tenure per Company:</strong>
                           {stability.get('Average Tenure per Company')}
                       </p>
                       <p style="margin: 6px 0;"><strong>Assessment:</strong>
                           {stability.get('Stability Assessment')}
                       </p>
                   </div>

                   <div style="border: 1px solid #eee; border-radius: 12px; padding: 16px;
                               box-shadow: 0 6px 20px rgba(0, 0, 0, 0.30); background-color: #f9f9f9;">
                       <h3 style="margin-top: 0; font-size: 18px;">Tone Detection</h3>
                       <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                   </div>
               </div>
            """

        def find_emoji(interpretation=''):
            emoji_map = {
                'Leadership': '\U0001F60A',  # 😊
                'Managerial': '\U0001F468\u200D\U0001F4BC',  # 👨‍💼
                'Individual Contributions': '\U0001F9CD',  # 🧍
                'Confidence': '\U0001F512',  # 🔒
                'Problem-Solving': '\U0001F9E9',  # 🧩
                'Communication': '\U0001F4AC',  # 💬
                'Technical': '\U0001F6E0\ufe0f',  # 🛠️
            }
            return emoji_map.get(interpretation, '')

        for tone, details in tone_data.items():
            emoji = find_emoji(tone)
            html += f"""
               <tr>
                 <td>{emoji} <strong>{tone}: </strong></td>
                 <td style="text-align: right;">{details.get('Keyword Count')}</td>
               </tr>"""
        html += f"""
               </table>
               </div>
               </div>
           """
        return html

    def process_purchase_receipt(self):
        """
        Main entry point to parse a resume.
        It sends the uploaded file to ScanDoc,
        interprets the response, and updates or creates partner,
        candidate, and
        applicant records. Also attaches the resume and
        adds sentiment analysis.

        :return: Action to open the related applicant form view.
        """
        self.ensure_one()

        # Get ScanDoc API Auth Key
        auth_key = self.env['ir.config_parameter'].sudo().get_param(
            'wb_scandoc_integration.scandoc_auth_key')
        if not auth_key:
            raise UserError(_(
                "Missing ScanDoc authentication key in system parameters."
            ))

        if not self.file or not self.file_name:
            raise UserError("Please upload a valid file.")

        # Prepare file and metadata
        file_content = ''
        try:
            file_content = base64.b64decode(self.file)
        except Exception as e:
            raise UserError(_("Error decoding uploaded file: %s") % str(e))

        # Detect MIME type dynamically
        mimetype, encoding = mimetypes.guess_type(self.file_name)
        mimetype = mimetype or 'application/octet-stream'

        # Optional: Validate allowed file types
        allowed_mimetypes = [
            'application/pdf', 'image/jpeg', 'image/png',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
            'application/msword',  # .doc
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # .xlsx
            'application/vnd.ms-excel',  # .xls
        ]
        if mimetype not in allowed_mimetypes:
            raise UserError(_(
                "Unsupported file type: %s. Please upload PDF, DOCX, JPG or PNG files only."
            ) % mimetype)

        # Example logging
        mimetype = (mimetypes.guess_type(self.file_name)[0]
                    or 'application/octet-stream')
        url = ("https://scandocapi--scandoc-api."
               "us-central1.hosted.app/api/documents/scan")

        try:
            # Send file to ScanDoc
            doc_type_map = {
                "Delivery Challan": "DeliveryChalaan",
                "Vendor Bill": "VendorBill",
                "Resume": "Resume",
            }
            doc_type = doc_type_map.get(self.doc_type, self.doc_type)
            if not doc_type:
                raise UserError("Document type not specified or incorrect.")

            response = requests.post(
                url,
                data={'authKey': auth_key, 'doc_type': doc_type},
                files=[('file', (self.file_name, file_content, mimetype))]
            )
            parsed_data = response.json()
            if parsed_data.get('error'):
                raise ValidationError(_(f"{parsed_data.get('error')}"))
            if not parsed_data.get('user') or not parsed_data.get('user').get('remainingScans') or parsed_data.get('user').get('remainingScans') < 0:
                raise ValidationError(_("You exceed your Scandoc Credit Limit. Please purchase new credits."))
            self.env["ir.config_parameter"].sudo().set_param(
                "wb_scandoc_integration.scandoc_credit", parsed_data.get('user').get('remainingScans')
            )
        except requests.exceptions.RequestException as e:
            raise UserError(f"ScanDoc API request failed: {e}")
        self.file_scanned = True

        # Initialize dictionaries for storing model values
        api_data = parsed_data.get('extractedData')
        user_data = parsed_data.get('user')
        remaining_scans = user_data.get('remainingScans')
        used_scan = user_data.get('totalScansUsed')
        company = self.env.company
        company.sudo().write({
                'remaining_credit': remaining_scans,
                'used_credit': used_scan,
            })
        if not api_data or not isinstance(api_data, dict) or not api_data.keys():
            raise ValidationError(_("Please upload a valid file — no readable data could be extracted."))
        gstin_number = None

        # GSTIN regex (15 characters, standard format)
        extracted_text = ""

        # If PDF
        if mimetype == "application/pdf":
            try:
                pdf_file = io.BytesIO(file_content)
                reader = PdfReader(pdf_file)
                for page in reader.pages:
                    extracted_text += page.extract_text() or ""
            except Exception as e:
                _logger.warning("PDF GSTIN extraction failed: %s", e)

        # If DOCX
        elif mimetype in [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel"
        ]:
            try:
                wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
                extracted_text = ""
                for sheet in wb.worksheets:
                    for row in sheet.iter_rows(values_only=True):
                        row_text = " ".join([str(cell) for cell in row if cell])
                        if row_text.strip():
                            extracted_text += " " + row_text
                # Excel text extracted successfully
            except Exception as e:
                _logger.warning("Excel GSTIN extraction failed: %s", e)

        # If Image (PNG/JPG) – use OCR
        elif mimetype in ["image/jpeg", "image/png"]:
            try:
                 # Open the image
                image = Image.open(io.BytesIO(file_content))

                # Convert to grayscale (helps simplify the text extraction)
                image = image.convert('L')

                # Resize the image to make text clearer (doubling the resolution)
                image = image.resize((image.width * 2, image.height * 2))  # Experiment with this factor

                # Thresholding: Convert the image into a binary format (black and white)
                image = image.point(lambda p: p > 180 and 255)  # Adjust threshold value (180) as needed

                # Invert the image colors (make text black and background white)
                image = ImageOps.invert(image)

                # Optional: Apply median filter (reduces noise) and sharpen the image
                image = image.filter(ImageFilter.MedianFilter(3))  # Try different filter sizes (3, 5, etc.)
                image = image.filter(ImageFilter.SHARPEN)

                # Enhance contrast to make text stand out more clearly
                enhancer = ImageEnhance.Contrast(image)
                image = enhancer.enhance(2)  # Try different values for better contrast

                # Use pytesseract to extract the text
                custom_config = r'--oem 3 --psm 6'  # Use LSTM OCR model
                extracted_text = pytesseract.image_to_string(image, config=custom_config)
            except Exception as e:
                _logger.warning("OCR GSTIN extraction failed: %s", e)
                return ""
            extracted_text = extracted_text.replace("\n", " ").replace("\r", " ").strip()
        # Regular expression for GST number
        gstin_pattern = r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]{3}\b"
        # Find GSTIN matches in the extracted text
        gstin_matches = re.findall(gstin_pattern, extracted_text)

        # Clean extracted text (remove newlines, extra spaces, etc.)
        extracted_text = extracted_text.replace("\n", " ").replace("\r", " ").strip()

        # Regular expression for GST number
        gstin_pattern = r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]{3}\b"

        # Find GSTIN matches in the extracted text
        gstin_matches = re.findall(gstin_pattern, extracted_text)

        if gstin_matches:
            gstin_number = gstin_matches[0]
        else:
            gstin_number = ''
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'incoming'),
            ('warehouse_id.company_id', '=', self.env.company.id)
        ], limit=1)
        if not picking_type:
            raise ValueError("No Incoming Picking Type found for this company.")

        # 2️⃣ Get or create partner (Consignor = vendor)
        partner = self.env['res.partner'].search([
            ('name', '=', api_data.get('Consignor Name'))
        ], limit=1)

        if not partner:
            partner = self.env['res.partner'].create({
                'name': api_data.get('Consignor Name'),
                'street': api_data.get('Consignor Address'),
                'company_type': 'company',
            })

        # 3️⃣ Prepare stock.move lines
        move_lines = []
        for item in api_data.get('Items', []):
            product = self.env['product.product'].search([
                ('default_code', '=', item.get('HSN/SAC'))
            ], limit=1)

            if not product:
                # Create placeholder product if not exists
                product = self.env['product.product'].create({
                    'name': item.get('Description'),
                    'default_code': item.get('HSN/SAC'),
                    'type': 'consu',
                    'uom_id': self.env.ref('uom.product_uom_unit').id,
                })

            move_lines.append((0, 0, {
                'description_picking': item.get('Description'),
                'product_id': product.id,
                'product_uom_qty': float(item.get('Quantity', 0)),
                'product_uom': product.uom_id.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': picking_type.default_location_dest_id.id,
            }))
        challan_date_str = api_data.get("Challan Date")
        scheduled_date = False
        if challan_date_str:
            challan_date_str = challan_date_str.strip()
            # Process raw challan date string
            try:
                scheduled_date = self.parse_date(challan_date_str)
            except ValueError:
                raise UserError(_("Invalid date format in Challan Date: %s") % challan_date_str)

        challan_number = api_data.get("Challan Number")

        # ✅ Check if challan number already exists
        if challan_number:
            exists = self.env['stock.picking'].search([('challan_number', '=', challan_number)])
            if exists:
                raise ValidationError(_("A record with Challan Number %s already exists!") % challan_number)
        # 4️⃣ Create the picking
        picking_vals = {
            'picking_type_id': picking_type.id,
            'partner_id': partner.id,
            'origin': api_data.get('Reference Number') or api_data.get('Challan Number'),
            'scheduled_date': scheduled_date,
            'move_ids': move_lines,
            'challan_number':api_data.get('Challan Number'),
            'vehicle_number':api_data.get("Transport Details", {}).get("Vehicle Number"),
            'transport_name':api_data.get("Transport Details", {}).get("Transporter Name"),
            'dispatch_location':api_data.get('Dispatch From'),
            'transport_doc_no': api_data.get("Transport Details", {}).get("LR Number"),
        }

        picking = self.env['stock.picking'].create(picking_vals)
        picking.write({'vendor_gst_number': False})
        picking.write({'vendor_gst_number': gstin_number or ''})
        # # Attach the uploaded resume file
        self.env['ir.attachment'].sudo().create({
            'name': self.file_name,
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'type': 'binary',
            'datas': self.file,
            'mimetype': mimetype,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _calculate_line_pricing(self, item):
        """
        Intelligently calculate quantity and unit price from various possible field combinations.
        Handles scenarios where API extracts different field names or misinterprets data.
        
        :param item: Line item dictionary from ScanDoc API
        :return: tuple (quantity, unit_price)
        """
        # Get quantity with various possible field names
        quantity_fields = ['Quantity', 'Qty', 'Units', 'Count', 'No.', 'Pieces']
        quantity = 1.0  # Default quantity
        
        for field in quantity_fields:
            if item.get(field):
                try:
                    quantity = float(self._clean_price_value(item.get(field, 1)))
                    if quantity > 0:
                        # Found quantity from field
                        break
                except (ValueError, TypeError):
                    continue
        
        if quantity <= 0:
            quantity = 1.0
            # Using default quantity
        
        # Get all possible price-related fields
        price_fields = {
            'unit_price': ['Unit Price', 'Price', 'Rate', 'Unit Rate', 'Price Per Unit', 'Each'],
            'line_total': ['Amount', 'Total', 'Line Total', 'Subtotal', 'Total Amount', 'Line Amount'],
            'extended': ['Extended Price', 'Extended Amount', 'Extension', 'Net Amount']
        }
        
        # Extract and clean all available price values
        extracted_prices = {}
        
        for category, fields in price_fields.items():
            for field in fields:
                if item.get(field):
                    try:
                        value = self._clean_price_value(item.get(field, 0))
                        if value > 0:
                            extracted_prices[f"{category}_{field}"] = value
                            # Found price category from field
                    except (ValueError, TypeError):
                        continue
        
        # Scenario analysis and unit price calculation
        unit_price = 0.0
        
        # Scenario 1: Line total/amount available - calculate unit price
        line_totals = [v for k, v in extracted_prices.items() if k.startswith('line_total_') or k.startswith('extended_')]
        if line_totals:
            line_total = max(line_totals)  # Use the largest if multiple
            unit_price = line_total / quantity
            # Calculated unit price from line total
            return quantity, unit_price
        
        # Scenario 2: Unit price available - validate it makes sense
        unit_prices = [v for k, v in extracted_prices.items() if k.startswith('unit_price_')]
        if unit_prices:
            raw_unit_price = max(unit_prices)  # Use the largest if multiple
            
            # Validation: Check if this might actually be a line total
            calculated_total = raw_unit_price * quantity
            
            # If the calculated total is unreasonably high, assume it's a misnamed line total
            if quantity > 1 and raw_unit_price > 1000:
                # Unit price seems too high, treating as line total
                unit_price = raw_unit_price / quantity
            else:
                unit_price = raw_unit_price
                # Using extracted unit price
            return quantity, unit_price
        
        # Scenario 3: Cross-validation when both types are available
        if extracted_prices:
            # Use any available price value and try to make sense of it
            all_values = list(extracted_prices.values())
            largest_value = max(all_values)
            smallest_value = min(all_values)
            
            # If there's a big difference, larger is likely line total, smaller is unit price
            if len(all_values) > 1 and largest_value > smallest_value * quantity * 0.8:
                unit_price = largest_value / quantity  # Treat larger as line total
                # Using largest value as line total
            else:
                unit_price = smallest_value  # Treat smaller as unit price
                # Using smallest value as unit price
            return quantity, unit_price
        
        # Scenario 4: Fallback - no price information found
        _logger.warning("   - No valid price information found in item, using 0.0")
        return quantity, 0.0

    def parse_date(self, date_str):
        if not date_str:
            raise ValueError("Date string cannot be empty")
        
        # Clean the date string
        date_str = str(date_str).strip()
        
        # List of supported date formats
        date_formats = [
            "%d/%m/%Y",    # 31/08/2025
            "%m/%d/%Y",    # 08/31/2025
            "%Y-%m-%d",    # 2025-08-31
            "%d-%m-%Y",    # 31-08-2025
            "%m-%d-%Y",    # 08-31-2025
            "%d-%m-%y",    # 31-08-25 (2-digit year)
            "%m-%d-%y",    # 08-31-25 (2-digit year)
            "%d/%m/%y",    # 31/08/25 (2-digit year)
            "%m/%d/%y",    # 08/31/25 (2-digit year)
            "%Y/%m/%d",    # 2025/08/31
            "%y/%m/%d",    # 25/08/31 (2-digit year)
            "%d.%m.%Y",    # 31.08.2025
            "%d.%m.%y",    # 31.08.25
            "%Y.%m.%d",    # 2025.08.31
            "%d %b %Y",    # 31 Aug 2025 (abbreviated month)
            "%d %B %Y",    # 31 August 2025 (full month name)
            "%b %d, %Y",   # Aug 31, 2025
            "%B %d, %Y",   # August 31, 2025
            "%d-%b-%Y",    # 31-Aug-2025
            "%d-%B-%Y",    # 31-August-2025
            "%d-%b-%y",    # 18-Sep-25 (the problematic format)
            "%d-%B-%y",    # 18-September-25
            "%d/%b/%Y",    # 18/Sep/2025
            "%d/%b/%y",    # 18/Sep/25
            "%d %b %y",    # 18 Sep 25
            "%d %B %y",    # 18 September 25
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        raise ValueError(f"Date format not recognized: {date_str}")

    def _detect_currency(self, data):
        """
        Detect and map currency from ScanDoc response data with enhanced logging.
        Handles both currency names and symbols with proper mapping.
        """
        currency_mapping = {
            # Currency symbols to currency codes
            'R': 'ZAR',      # South African Rand symbol
            'r': 'ZAR',      # Lowercase variant
            '$': 'USD',      # US Dollar symbol
            '€': 'EUR',      # Euro symbol
            '£': 'GBP',      # British Pound symbol
            '¥': 'JPY',      # Japanese Yen symbol
            '₹': 'INR',      # Indian Rupee symbol
            # Currency codes (direct mapping)
            'ZAR': 'ZAR',    # South African Rand
            'USD': 'USD',    # US Dollar
            'EUR': 'EUR',    # Euro
            'GBP': 'GBP',    # British Pound
            'JPY': 'JPY',    # Japanese Yen
            'INR': 'INR',    # Indian Rupee
            'CAD': 'CAD',    # Canadian Dollar
            'AUD': 'AUD',    # Australian Dollar
            'CHF': 'CHF',    # Swiss Franc
            'CNY': 'CNY',    # Chinese Yuan
        }
        
        # Check for currency in data
        detected_currency = None
        currency_value = data.get('Currency', '').strip()
        
        # Start currency detection process
        
        if currency_value:
            # Direct lookup in mapping
            detected_currency = currency_mapping.get(currency_value)
            # Direct currency mapping found
        
        # If no direct match, try to find currency symbols in the data
        if not detected_currency:
            # Look for currency symbols in various fields
            fields_to_check = ['Total', 'Subtotal', 'Amount', 'Currency', 'TotalAmount']
            # No direct match, checking fields for currency symbols
            
            for field in fields_to_check:
                field_value = str(data.get(field, ''))
                if field_value:
                    # Checking field for currency symbols
                    for symbol, currency_code in currency_mapping.items():
                        if symbol in field_value:
                            detected_currency = currency_code
                            # Currency symbol found and mapped
                            break
                if detected_currency:
                    break
        
        if detected_currency:
            # Use the enhanced currency activation method
            # Currency detected, proceeding with activation
            currency_record = self._activate_currency(detected_currency)
            if currency_record:
                # Currency ready for use
                return currency_record
            else:
                _logger.error(f"❌ Failed to activate or create currency: {detected_currency}")
        
        # No currency detected, will use company default
        return None

    def _activate_currency(self, currency_code):
        """
        Manually activate a specific currency by currency code with enhanced verification.
        If currency doesn't exist, create it with proper symbol configuration.
        
        :param currency_code: Currency code (e.g., 'ZAR', 'USD', 'EUR')
        :return: Currency record if found/created and activated, None otherwise
        """
        # First check for active currency
        currency_record = self.env['res.currency'].search([
            ('name', '=', currency_code),
            ('active', '=', True)
        ], limit=1)
        
        if currency_record:
            # Currency was already active
            return currency_record
        
        # Check for inactive currency (including inactive ones)
        currency_record = self.env['res.currency'].with_context(active_test=False).search([
            ('name', '=', currency_code)
        ], limit=1)
        
        if currency_record:
            if not currency_record.active:
                try:
                    currency_record.active = True
                    # Manually activated currency
                except Exception as e:
                    _logger.error(f"❌ Failed to manually activate currency {currency_code}: {str(e)}")
                    return None
            
            # Verify the currency has proper symbol configuration
            expected_symbols = {
                'ZAR': 'R',
                'USD': '$',
                'EUR': '€',
                'GBP': '£',
                'JPY': '¥',
                'INR': '₹'
            }
            
            expected_symbol = expected_symbols.get(currency_code)
            if expected_symbol and currency_record.symbol != expected_symbol:
                _logger.warning(f"⚠️ Currency {currency_code} symbol mismatch: Expected '{expected_symbol}', found '{currency_record.symbol}'")
                try:
                    currency_record.symbol = expected_symbol
                    # Updated currency symbol
                except Exception as e:
                    _logger.error(f"❌ Failed to update currency symbol: {str(e)}")
            
            return currency_record
        else:
            # Currency doesn't exist, try to create it
            # Creating new currency record
            return self._create_currency(currency_code)

    def _create_currency(self, currency_code):
        """
        Create a new currency record in Odoo with proper symbol configuration.
        
        :param currency_code: Currency code (e.g., 'ZAR', 'USD', 'EUR')
        :return: Currency record if created successfully, None otherwise
        """
        # Enhanced currency definitions with proper symbols and formatting
        currency_definitions = {
            'ZAR': {'name': 'ZAR', 'full_name': 'South African Rand', 'symbol': 'R', 'rounding': 0.01, 'position': 'before'},
            'USD': {'name': 'USD', 'full_name': 'US Dollar', 'symbol': '$', 'rounding': 0.01, 'position': 'before'},
            'EUR': {'name': 'EUR', 'full_name': 'Euro', 'symbol': '€', 'rounding': 0.01, 'position': 'after'},
            'GBP': {'name': 'GBP', 'full_name': 'British Pound', 'symbol': '£', 'rounding': 0.01, 'position': 'before'},
            'JPY': {'name': 'JPY', 'full_name': 'Japanese Yen', 'symbol': '¥', 'rounding': 1.0, 'position': 'before'},
            'INR': {'name': 'INR', 'full_name': 'Indian Rupee', 'symbol': '₹', 'rounding': 0.01, 'position': 'before'},
            'CAD': {'name': 'CAD', 'full_name': 'Canadian Dollar', 'symbol': 'CAD$', 'rounding': 0.01, 'position': 'before'},
            'AUD': {'name': 'AUD', 'full_name': 'Australian Dollar', 'symbol': 'AUD$', 'rounding': 0.01, 'position': 'before'},
            'CHF': {'name': 'CHF', 'full_name': 'Swiss Franc', 'symbol': 'CHF', 'rounding': 0.01, 'position': 'before'},
            'CNY': {'name': 'CNY', 'full_name': 'Chinese Yuan', 'symbol': '¥', 'rounding': 0.01, 'position': 'before'},
        }
        
        currency_def = currency_definitions.get(currency_code)
        if not currency_def:
            _logger.warning(f"No definition found for currency {currency_code}")
            return None
        
        try:
            # Create currency with enhanced symbol configuration
            currency_vals = {
                'name': currency_def['name'],
                'symbol': currency_def['symbol'],
                'rounding': currency_def['rounding'],
                'position': currency_def['position'],
                'active': True,
            }
            
            # Add full_name only if it exists in the currency model
            if hasattr(self.env['res.currency'], 'full_name'):
                currency_vals['full_name'] = currency_def['full_name']
                
            currency_record = self.env['res.currency'].create(currency_vals)
            
            # Successfully created currency
            
            # Verify currency configuration
            if currency_record.symbol == currency_def['symbol']:
                pass  # Currency symbol verification passed
            else:
                _logger.warning(f"⚠️ Currency symbol mismatch: Expected '{currency_def['symbol']}', got '{currency_record.symbol}'")
            
            return currency_record
        except Exception as e:
            _logger.error(f"❌ Failed to create currency {currency_code}: {str(e)}")
            return None

    def test_currency_activation(self):
        """
        Test method to activate common currencies programmatically.
        This can be called to ensure required currencies are available.
        """
        common_currencies = ['ZAR', 'USD', 'EUR', 'GBP', 'JPY', 'INR']
        activated_currencies = []
        
        for currency_code in common_currencies:
            currency = self._activate_currency(currency_code)
            if currency:
                activated_currencies.append(currency_code)
        
        # Currency activation test completed
        return activated_currencies

    def _clean_price_value(self, price_str):
        """
        Clean price string by removing currency symbols and converting to float.
        
        :param price_str: Price string that might contain currency symbols
        :return: Float value of the price
        """
        if not price_str:
            return 0.0
            
        # Convert to string if it's not already
        price_str = str(price_str).strip()
        
        if not price_str:
            return 0.0
            
        # Remove common currency symbols
        currency_symbols = ['R', '$', '€', '£', '¥', '₹', '₦', '₵', '₡', '₪', '₫', '₩', '₽', '₴', '₸', '₹']
        
        # Clean the price string
        cleaned_price = price_str
        for symbol in currency_symbols:
            cleaned_price = cleaned_price.replace(symbol, '').strip()
        
        # Remove commas and other formatting
        cleaned_price = cleaned_price.replace(',', '').replace(' ', '')
        
        try:
            return float(cleaned_price)
        except (ValueError, TypeError):
            _logger.warning(f"Could not convert price '{price_str}' to float, returning 0.0")
            return 0.0

    def process_purchase_order(self):
        """
        Production-ready main entry point for document processing.
        Includes comprehensive error handling, validation, and logging.
        
        :return: Action to open the related document form view.
        """
        self.ensure_one()
        
        # 🔧 FIX: Force save the wizard state before validation check
        # This ensures confirmation state is persisted between wizard calls
        try:
            if hasattr(self, '_origin') and self._origin:
                # If this is a modified record, save it to ensure state persistence
                self.sudo()._flush_recordset()
                # Wizard state flushed for persistence
        except Exception as e:
            _logger.warning("⚠️ Could not flush wizard state: %s", str(e))
        
        # Processing start - checking confirmation state and mismatch detection
        
        # Check if company validation confirmation is required
        if self.company_mismatch_detected and not self.confirm_external_processing:
            _logger.warning("🔄 Company mismatch detected but user has not confirmed - showing confirmation UI")
            raise UserError(
                "⚠️ Security Confirmation Required!\n\n"
                "This invoice is addressed to an external company. "
                "Please review the details above and check the confirmation box "
                "if you are authorized to process this external invoice."
            )
        
        # try:
            # Pre-processing validation and security checks
        self._check_dependencies()
        self._validate_file_security()
        self._log_processing_start()
        # Check user permissions
        if not self.env.user.has_group('wb_scandoc_integration.group_po_scanner'):
            raise AccessError("You don't have permission to process documents")
        # Get and validate ScanDoc API credentials
        auth_key = self._get_scandoc_auth_key()
        # Process the document with enhanced error handling
        return self._process_document_safe(auth_key)
    
    def _get_scandoc_auth_key(self):
        """Get and validate ScanDoc authentication key"""
        auth_key = self.env['ir.config_parameter'].sudo().get_param(
            'wb_scandoc_integration.scandoc_auth_key')
        if not auth_key:
            raise UserError(
                "ScanDoc authentication key not configured. "
                "Please configure it in Settings > Technical > System Parameters."
            )
        return auth_key
    
    def _process_document_safe(self, auth_key):
        """Process document with comprehensive error handling"""
        
        # 🚀 NEW: Check if we already have extracted data stored
        stored_data = self._get_stored_data()
        if stored_data:
            # Using stored extracted data, skipping API call
            return self._process_extracted_data(stored_data)
        
        # No stored data found, calling ScanDoc API

        # Prepare file and metadata
        file_content = ''
        try:
            file_content = base64.b64decode(self.file)
        except Exception as e:
            raise UserError(_("Error decoding uploaded file: %s") % str(e))

        # Detect MIME type dynamically
        mimetype, encoding = mimetypes.guess_type(self.file_name)
        mimetype = mimetype or 'application/octet-stream'

        # Optional: Validate allowed file types
        allowed_mimetypes = [
            'application/pdf', 'image/jpeg', 'image/png',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
            'application/msword',  # .doc
        ]
        if mimetype not in allowed_mimetypes:
            raise UserError(_(
                "Unsupported file type: %s. Please upload PDF, DOCX, JPG or PNG files only."
            ) % mimetype)

        # Example logging
        mimetype = (mimetypes.guess_type(self.file_name)[0]
                    or 'application/octet-stream')
        # url = ("https://scandocapi--scandoc-api."
        #        "us-central1.hosted.app/api/documents/scan")
        url = "https://scandocapi--scandoc-api.us-central1.hosted.app/external-extract"

        try:
            # Validate dependencies before making request
            if requests is None:
                raise UserError("Python 'requests' library not installed. Please install it.")
                
            # Send file to ScanDoc with timeout and retry logic
            # url = ("https://scandocapi--scandoc-api."
            #        "us-central1.hosted.app/api/documents/scan")
            url = "https://scandocapi--scandoc-api.us-central1.hosted.app/external-extract"
            
            timeout = 120  # 2 minutes timeout for large files
            max_retries = 2
            response = None  # Initialize response variable
            
            for attempt in range(max_retries + 1):
                try:
                    # Sending document to ScanDoc API
                    
                    response = requests.post(
                        url, 
                        data={
                            'authKey': auth_key, 
                            'doc_type': 'invoice'
                        }, 
                        files=[('file', (self._get_safe_filename(), file_content, mimetype))],
                        timeout=timeout
                    )
                    
                    # Check HTTP status
                    response.raise_for_status()
                    break
                    
                except requests.exceptions.Timeout:
                    if attempt < max_retries:
                        _logger.warning("Request timeout, retrying... (attempt %d/%d)", attempt + 1, max_retries + 1)
                        continue
                    else:
                        raise UserError("Request timeout. The document may be too large or the service is busy.")
                        
                except requests.exceptions.ConnectionError:
                    if attempt < max_retries:
                        _logger.warning("Connection error, retrying... (attempt %d/%d)", attempt + 1, max_retries + 1)
                        continue
                    else:
                        raise UserError("Cannot connect to ScanDoc API. Please check your internet connection.")
                        
                except requests.exceptions.HTTPError as e:
                    if response and response.status_code == 401:
                        raise UserError("Invalid ScanDoc API key. Please check your credentials.")
                    elif response and response.status_code == 429:
                        raise UserError("Rate limit exceeded. Please try again later.")
                    elif response and response.status_code >= 500:
                        if attempt < max_retries:
                            _logger.warning("Server error, retrying... (attempt %d/%d)", attempt + 1, max_retries + 1)
                            continue
                        else:
                            raise UserError("ScanDoc API server error. Please try again later.")
                    else:
                        status_code = response.status_code if response else 'Unknown'
                        raise UserError("API request failed with status %s: %s" % (status_code, str(e)))
            
            # Validate we have a response after retry loop
            if response is None:
                raise UserError("Failed to get response from ScanDoc API after all retry attempts.")
            
            # Parse response safely
            try:
                parsed_data = response.json()
            except ValueError as e:
                _logger.error("Invalid JSON response from ScanDoc API: %s", response.text[:500])
                raise UserError("Invalid response from ScanDoc API. Please contact support.")
            
            # Validate response structure
            if not isinstance(parsed_data, dict):
                raise UserError("Unexpected response format from ScanDoc API")
                
            # Check for API errors
            if parsed_data.get('error'):
                error_msg = parsed_data.get('error', 'Unknown API error')
                _logger.error("ScanDoc API error: %s", error_msg)
                raise ValidationError("ScanDoc API error: %s" % error_msg)
            
            # Check credit limits with better error handling
            user_data = parsed_data.get('user', {})
            remaining_scans = user_data.get('remainingScans')
            used_credits = user_data.get('totalScansUsed')


            # 4. UPDATE CREDITS ON COMPANY
            # ------------------------------------------------------------------
            company = self.env.company
            company.sudo().write({
                'remaining_credit': remaining_scans,
                'used_credit': used_credits,
            })
            if remaining_scans is None:
                _logger.warning("No scan limit information in API response")
            elif remaining_scans < 0:
                raise ValidationError(
                    "You have exceeded your ScanDoc credit limit. "
                    "Please purchase additional credits to continue processing documents."
                )
            # Update scan credits safely
            try:
                user_data = parsed_data.get('user', {})
                remaining_scans = user_data.get('remainingScans')
                if remaining_scans is not None:
                    self.env["ir.config_parameter"].sudo().set_param(
                        "wb_scandoc_integration.scandoc_credit", str(remaining_scans)
                    )
            except Exception as e:
                _logger.warning("Failed to update scan credits: %s", str(e))
                
            # 🚀 NEW: Store the extracted data before processing
            self._store_extracted_data(parsed_data)
            
            # Process the document data
            return self._process_extracted_data(parsed_data)
            
        except Exception as e:
            if requests and hasattr(requests, 'exceptions') and isinstance(e, requests.exceptions.RequestException):
                _logger.error("ScanDoc API request failed: %s", str(e))
                raise UserError("ScanDoc API request failed: %s" % str(e))
            else:
                # Re-raise other exceptions
                raise
    
    def _validate_company_match(self, data):
        """
        Validate if the invoice is addressed to the current company.
        Sets warning flags if there's a mismatch for user review.
        
        :param data: Extracted data from ScanDoc API
        :return: True if validation passes or can be deferred to user
        """
        # Get company information from invoice
        invoice_company_name = ''
        invoice_company_address = ''

        if data.get('Company Name', ''):
            invoice_company_name = data.get('Company Name', '').strip()
        if data.get('Company Address', ''):
            invoice_company_address = data.get('Company Address', '').strip()
        
        # Get current Odoo company information
        current_company = self.env.company
        current_company_name = current_company.name.strip() if current_company.name else ''
        
        # Build current company address for comparison
        current_company_address_parts = [
            current_company.street or '',
            current_company.street2 or '',
            current_company.city or '',
            current_company.state_id.name if current_company.state_id else '',
            current_company.zip or '',
            current_company.country_id.name if current_company.country_id else ''
        ]
        current_company_address = ', '.join([part for part in current_company_address_parts if part]).strip()
        
        # Company validation check
        # Check invoice company details
        # Check current company details
        # Check invoice address
        # Check current address
        
        # Skip validation if no company information found in invoice
        if not invoice_company_name:
            _logger.warning("⚠️ No company name found in invoice - proceeding with caution")
            return True
        
        # Check for company name match (fuzzy matching for variations)
        def normalize_company_name(name):
            """Normalize company name for comparison"""
            if not name:
                return ''
            # Remove common company suffixes and normalize
            import re
            normalized = re.sub(r'\b(ltd|limited|inc|incorporated|corp|corporation|llc|pty|pvt)\b', '', name.lower())
            normalized = re.sub(r'[^\w\s]', '', normalized)  # Remove punctuation
            normalized = ' '.join(normalized.split())  # Normalize whitespace
            return normalized
        
        normalized_invoice_company = normalize_company_name(invoice_company_name)
        normalized_current_company = normalize_company_name(current_company_name)
        
        # Check for exact or fuzzy match
        company_match = False
        if normalized_current_company and normalized_invoice_company:
            # Check if one company name contains the other (for variations)
            if (normalized_current_company in normalized_invoice_company or 
                normalized_invoice_company in normalized_current_company):
                company_match = True
            
            # Check for high similarity (at least 80% match)
            from difflib import SequenceMatcher
            similarity = SequenceMatcher(None, normalized_current_company, normalized_invoice_company).ratio()
            if similarity >= 0.8:
                company_match = True
                # Company names match with similarity
        
        if company_match:
            # Company validation passed - invoice is for current company
            # Clear any previous mismatch flags
            self.company_mismatch_detected = False
            self.external_invoice_details = ""
            self.confirm_external_processing = False
            return True
        
        # Company mismatch detected
        _logger.warning("🚨 COMPANY MISMATCH DETECTED!")
        _logger.warning("   This invoice is NOT addressed to your company!")
        
        # Check current confirmation state FIRST
        # Check current confirmation state
        # Check company mismatch detected flag
        
        # Check if user has already confirmed in this session
        if self.confirm_external_processing:
            _logger.warning("✅ User %s confirmed processing external invoice for '%s'", 
                           self.env.user.name, invoice_company_name)
            # Create audit log for external invoice processing
            self._create_external_invoice_audit_log(invoice_company_name, current_company_name)
            return True
        
        # Set warning details for user review (only if not already confirmed)
        mismatch_details = f"""⚠️ COMPANY MISMATCH DETECTED!

📄 Invoice Company: {invoice_company_name}
🏢 Your Company: {current_company_name}

📍 Invoice Address: {invoice_company_address or 'Not specified'}
📍 Your Address: {current_company_address or 'Not specified'}

🚨 This invoice appears to be for a different company!
Please confirm if you want to process this external invoice."""
        
        # Set the validation fields (only if not already set)
        if not self.company_mismatch_detected:
            self.company_mismatch_detected = True
            self.external_invoice_details = mismatch_details
            # Don't reset confirmation if user already set it
            if not hasattr(self, 'confirm_external_processing') or self.confirm_external_processing is None:
                self.confirm_external_processing = False
        
        # Log security event for audit trail
        _logger.warning("SECURITY AUDIT: User %s processing invoice for external company '%s' (Current: '%s')", 
                       self.env.user.name, invoice_company_name, current_company_name)
        
        # Return False to indicate validation failed but allow user to see confirmation UI
        _logger.warning("🔄 Company mismatch detected - showing confirmation UI to user")
        return False

    def _create_external_invoice_audit_log(self, invoice_company, current_company):
        """
        Create an audit log entry for external invoice processing.
        This helps with security monitoring and compliance.
        """
        try:
            # Create audit log entry
            audit_message = (
                f"EXTERNAL INVOICE PROCESSED: User '{self.env.user.name}' "
                f"(ID: {self.env.user.id}) processed invoice for external company '{invoice_company}' "
                f"while logged into '{current_company}'. "
                f"File: {self.file_name or 'Unknown'}, "
                f"Timestamp: {fields.Datetime.now()}"
            )
            
            # Log to server logs
            _logger.warning("AUDIT: %s", audit_message)
            
            # Create a mail message for audit trail (attached to current user)
            self.env['mail.message'].sudo().create({
                'subject': '🚨 External Invoice Processed - Security Audit',
                'body': f"<p><strong>Security Audit Alert:</strong></p><p>{audit_message}</p>",
                'model': 'res.users',
                'res_id': self.env.user.id,
                'message_type': 'notification',
                'author_id': self.env.user.partner_id.id,
                'needaction': False,
            })
            
            # Log to system parameter for admin tracking
            audit_key = f'wb_scandoc_integration.external_invoice_audit_{fields.Datetime.now().strftime("%Y%m%d_%H%M%S")}'
            self.env['ir.config_parameter'].sudo().set_param(audit_key, audit_message)
            
        except Exception as audit_error:
            _logger.error("Failed to create audit log: %s", str(audit_error))
            # Don't fail the main process due to audit logging issues


    def _process_extracted_data(self, parsed_data):
        """Process ScanDoc API response and create a Purchase Order."""

        data = parsed_data.get('extractedData') or {}
        items = data.get("data", {}).get("items", [])
        if not items:
            raise UserError("Document is empty. No data extracted.")
            
        # --- Vendor Info ---
        vendor_vals = {
            'name': data.get('data').get('supplier_name') or 'Unknown Vendor',
            'street': data.get('data').get('supplier_address'),
            'vat': data.get('data').get('supplier_gstn', ''),
            'supplier_rank': 1,
        }

        vendor = self.env['res.partner'].sudo().search([
            '|', ('name', '=', vendor_vals['name']),
            ('vat', '=', vendor_vals['vat'])
        ], limit=1)
        if not vendor:
            vendor = self.env['res.partner'].sudo().create(vendor_vals)
        else:
            vendor.write(vendor_vals)

        # --- Purchase Order Info ---
        invoice_date_str = data.get('data').get('supplier_invoice_date')
        if invoice_date_str:
            parsed_date = self.parse_date(invoice_date_str)
        else:
            parsed_date = fields.Datetime.now()
        date_order = fields.Datetime.to_string(parsed_date)
        currency_record = self._detect_currency(data.get('data', {}))
        if not currency_record:
            currency_id = self.env.company.currency_id
        else:
            currency_id = currency_record
        po_vals = {
            'partner_id': vendor.id,
            'partner_ref': data.get('data').get('supplier_invoice_no', ''),
            'origin': data.get('data').get('additional_info', {}).get('po_no', ''),
            'date_order': date_order,
            'company_id': self.env.company.id,
            'currency_id': currency_id.id,
        }
        # --- PO Lines ---
        po_line_vals = []
        for item in data.get('data').get('items', []):
            product_name = item.get('item_name', 'Unnamed Product')
            quantity = float(item.get('quantity') or 1)
            # price_unit = float(item.get('item_rate') or 0)
            raw_rate = item.get('item_rate') or "0"
            clean_rate = re.sub(r'[^\d.]', '', raw_rate)  # keep only digits and dot
            price_unit = float(clean_rate or 0)
            hsn = item.get('hsn_code') or ''
            uom_name = item.get('uom', 'Unit')
            # Find/Create Product
            product = self.env['product.product'].sudo().search([('name', '=', product_name)], limit=1)
            if not product:
                uom = self.env['uom.uom'].search([('name', 'ilike', uom_name)], limit=1)
                if not uom:
                    uom = self.env['uom.uom'].search([('name', 'ilike', 'Unit')], limit=1)
                product = self.env['product.product'].sudo().create({
                    'name': product_name,
                    'uom_id': uom.id,
                    'default_code': hsn,
                })
            # Enhanced tax detection
            # tax_info = self._detect_and_process_taxes(data)
            tax_info = self._detect_and_process_taxes(data.get('data', {}))
            is_courier = 'COURIER' in product_name.upper()
            tax_ids = []
            if is_courier:
                if tax_info['courier_cgst_tax_id']:
                    tax_ids.append(tax_info['courier_cgst_tax_id'].id)
                if tax_info['courier_sgst_tax_id']:
                    tax_ids.append(tax_info['courier_sgst_tax_id'].id)
            else:
                if tax_info['cgst_tax_id']:
                    tax_ids.append(tax_info['cgst_tax_id'].id)
                if tax_info['sgst_tax_id']:
                    tax_ids.append(tax_info['sgst_tax_id'].id)

            po_line_vals.append((0, 0, {
                'product_id': product.id,
                'name': product_name,
                'product_qty': quantity,
                'product_uom_id': product.uom_id.id,
                'price_unit': price_unit,
                'tax_ids': [(6, 0, tax_ids)],
                # 'taxes_id': [(6, 0, [])],  # You can enhance tax detection later
            }))
        po_vals['order_line'] = po_line_vals
        # --- Create Purchase Order ---
        purchase_order = self.env['purchase.order'].sudo().create(po_vals)
        # --- Attach Original File ---
        mimetype, _ = mimetypes.guess_type(self.file_name)
        mimetype = mimetype or 'application/pdf'
        self.env['ir.attachment'].sudo().create({
            'name': self.file_name,
            'res_model': 'purchase.order',
            'res_id': purchase_order.id,
            'type': 'binary',
            'datas': self.file,
            'mimetype': mimetype,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': purchase_order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def safe_float(value):
        if not value:
            return 0.0

        if isinstance(value, (int, float)):
            return float(value)

        try:
            s = str(value)
            s = re.sub(r'[^0-9.-]', '', s)   # keep only digits, dot, minus

            if s in ("", "-", ".", "-.", ".-", None):
                return 0.0

            return float(s)
        except:
            return 0.0


    def _get_tax_ids(self, tax_rate):
        """Finds tax records by percentage."""
        taxes = self.env['account.tax'].sudo().search([
            ('amount', '=', float(tax_rate)),
            ('type_tax_use', '=', 'purchase')
        ])
        return taxes.ids

    def _detect_and_process_taxes(self, data):
        """
        Return:
            {
                'default_cgst_rate': 9.0,
                'default_sgst_rate': 9.0,
                'courier_cgst_rate': 9.0,
                'courier_sgst_rate': 9.0,
                'cgst_tax_id': <record>,
                'sgst_tax_id': <record>,
                ...
            }
        """
        tax_info = {
            'default_cgst_rate': None,
            'default_sgst_rate': None,
            'courier_cgst_rate': None,
            'courier_sgst_rate': None,
            'cgst_tax_id': None,
            'sgst_tax_id': None,
            'courier_cgst_tax_id': None,
            'courier_sgst_tax_id': None,
        }
        addl = data.get('additional_info')
        totals = data.get('totals', {})
        # 1. Courier-specific rates (explicit in JSON)
        courier_cgst = addl.get('courier_charges_cgst_rate')
        courier_sgst = addl.get('courier_charges_sgst_rate')
        if courier_cgst and courier_cgst.endswith('%'):
            tax_info['courier_cgst_rate'] = float(courier_cgst.rstrip('%'))
        if courier_sgst and courier_sgst.endswith('%'):
            tax_info['courier_sgst_rate'] = float(courier_sgst.rstrip('%'))
        raw_subtotal = totals.get('subtotal') or "0"
        clean_subtotal = re.sub(r'[^\d.]', '', str(raw_subtotal))
        subtotal = float(clean_subtotal or 0)
        # subtotal = float(totals.get('subtotal') or 0)
        total_cgst = float(totals.get('total_cgst') or 0)
        total_sgst = float(totals.get('total_sgst') or 0)

        if subtotal > 0 and (total_cgst > 0 or total_sgst > 0):
            if total_cgst > 0:
                tax_info['default_cgst_rate'] = round((total_cgst * 100) / subtotal, 2)
            if total_sgst > 0:
                tax_info['default_sgst_rate'] = round((total_sgst * 100) / subtotal, 2)

        # 3. Create / find tax records
        def get_tax(prefix, rate):
            if rate is None:
                return None
            name = f"{prefix} {rate}%"
            tax = self.env['account.tax'].sudo().search([
                ('name', '=ilike', name),
                ('type_tax_use', '=', 'purchase'),
                ('amount_type', '=', 'percent'),
                ('amount', '=', rate),
            ], limit=1)
            if not tax:
                # Find a tax group (required field)
                tax_group = self.env['account.tax.group'].sudo().search([
                    ('company_id', '=', self.env.company.id),
                    ('country_id', '=', self.env.company.country_id.id)
                ], limit=1)
                
                if not tax_group:
                     # Fallback to any tax group
                    tax_group = self.env['account.tax.group'].sudo().search([], limit=1)

                if not tax_group:
                    tax_group = self.env['account.tax.group'].sudo().create({
                        'name': 'Default Tax Group',
                        'company_id': self.env.company.id,
                        'country_id': self.env.company.country_id.id,
                    })

                country_id = self.env.company.country_id.id
                if not country_id:
                    country_id = self.env['res.country'].sudo().search([], limit=1).id

                tax = self.env['account.tax'].sudo().create({
                    'name': name,
                    'amount': rate,
                    'amount_type': 'percent',
                    'type_tax_use': 'purchase',
                    'company_id': self.env.company.id,
                    'tax_group_id': tax_group.id,
                    'country_id': country_id,
                })
                _logger.info("Created tax: %s", name)
            return tax

        # Default taxes
        tax_info['cgst_tax_id'] = get_tax('CGST', tax_info['default_cgst_rate'])
        tax_info['sgst_tax_id'] = get_tax('SGST', tax_info['default_sgst_rate'])

        # Courier taxes
        tax_info['courier_cgst_tax_id'] = get_tax('CGST', tax_info['courier_cgst_rate'])
        tax_info['courier_sgst_tax_id'] = get_tax('SGST', tax_info['courier_sgst_rate'])
        return tax_info

    def _extract_tax_amount(self, tax_value):
        """Extract numeric tax amount from tax field value."""
        if not tax_value:
            return 0
        
        # Convert to string and clean
        tax_str = str(tax_value).strip()
        
        # Remove currency symbols and extract numbers
        import re
        numbers = re.findall(r'[\d,]+\.?\d*', tax_str)
        
        if numbers:
            try:
                # Take the largest number (likely the tax amount)
                amounts = [float(num.replace(',', '')) for num in numbers]
                return max(amounts)
            except ValueError:
                pass
        
        return 0

    def _extract_tax_rate(self, tax_value, data):
        """Extract tax rate percentage from tax field or calculate from amounts."""
        if not tax_value:
            return 0
        
        tax_str = str(tax_value).strip().lower()
        
        # Look for percentage symbol
        if '%' in tax_str:
            import re
            percentages = re.findall(r'(\d+(?:\.\d+)?)%', tax_str)
            if percentages:
                try:
                    return float(percentages[0])
                except ValueError:
                    pass
        
        # Try to calculate tax rate from amounts
        tax_amount = self._extract_tax_amount(tax_value)
        if tax_amount > 0:
            subtotal = self._clean_price_value(data.get('Subtotal', 0))
            if subtotal > 0:
                calculated_rate = (tax_amount / subtotal) * 100
                # Round to common tax rates
                common_rates = [5, 12, 18, 28, 10, 15, 20, 25]
                for rate in common_rates:
                    if abs(calculated_rate - rate) < 1:  # Within 1% tolerance
                        return rate
                return round(calculated_rate, 2)
        
        return 0

    def _get_or_create_tax(self, tax_rate):
        """Get existing tax or create new one with the given rate."""
        if not tax_rate or tax_rate <= 0:
            return []
        
        # Search for existing tax
        taxes = self.env['account.tax'].sudo().search([
            ('amount', '=', float(tax_rate)),
            ('type_tax_use', '=', 'purchase'),
            ('company_id', '=', self.env.company.id)
        ], limit=1)  # Limit to 1 to avoid duplicates
        
        if taxes:
            # Found existing tax
            return [taxes[0].id]  # Return only the first tax ID as a list
        
        # Create new tax if not found
        try:
            # Find a tax group (required field)
            tax_group = self.env['account.tax.group'].sudo().search([
                ('company_id', '=', self.env.company.id),
                ('country_id', '=', self.env.company.country_id.id)
            ], limit=1)
            
            if not tax_group:
                 # Fallback to any tax group
                tax_group = self.env['account.tax.group'].sudo().search([], limit=1)

            if not tax_group:
                tax_group = self.env['account.tax.group'].sudo().create({
                    'name': 'Default Tax Group',
                    'company_id': self.env.company.id,
                    'country_id': self.env.company.country_id.id,
                })

            country_id = self.env.company.country_id.id
            if not country_id:
                country_id = self.env['res.country'].sudo().search([], limit=1).id

            new_tax = self.env['account.tax'].sudo().create({
                'name': f'Purchase Tax {tax_rate}%',
                'amount': float(tax_rate),
                'type_tax_use': 'purchase',
                'company_id': self.env.company.id,
                'tax_scope': 'consu',  # Consumption
                'tax_group_id': tax_group.id,
                'country_id': country_id,
            })
            # Created new tax
            return [new_tax.id]
        except Exception as e:
            _logger.error("❌ Failed to create tax %s%%: %s", tax_rate, str(e))
            return []

    def _get_line_tax_ids(self, item, tax_info):
        """Get tax IDs for a specific line item."""
        # First, check if the item has its own tax rate
        line_tax_fields = ['Tax Rate (%)', 'Tax %', 'Tax Rate', 'GST %', 'VAT %']
        for field in line_tax_fields:
            tax_value = item.get(field)
            if tax_value:
                try:
                    tax_rate = float(tax_value)
                    if tax_rate > 0:
                        return self._get_or_create_tax(tax_rate)
                except (ValueError, TypeError):
                    continue
        
        # If no line-level tax, use invoice-level tax
        if tax_info['has_invoice_level_tax'] and tax_info['default_tax_ids']:
            return tax_info['default_tax_ids']
        
        # Default: no tax
        return []

