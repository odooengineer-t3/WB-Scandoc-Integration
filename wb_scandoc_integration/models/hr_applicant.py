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
This module extends the HR Recruitment functionality in Odoo by introducing models
to store additional applicant information such as work experience, education details,
resume parsing integration, relevance scoring, and sentiment analysis.
"""
import json
import base64
import mimetypes
import requests
import logging
from odoo import models, fields , api, _
from odoo.exceptions import UserError, ValidationError
_logger = logging.getLogger(__name__)
import re


class HrApplicantWorkExperience(models.Model):
    """
    Stores work experience records related to an HR applicant.
    Each record includes the company name, role, and duration.
    """
    _name = "hr.applicant.work.experience"
    _description = "Work Experience for Applicants"
    _order = "duration DESC"

    applicant_id = fields.Many2one(
        "hr.applicant", string="Applicant", required=True, ondelete="cascade"
    )
    company_name = fields.Char(string="Company", required=True)
    role = fields.Char(string="Role", required=True)
    duration = fields.Char(string="Duration", required=True)
    start_date = fields.Char(string="Start Date")
    end_date = fields.Char(string="End Date")


class HrApplicantEducation(models.Model):
    """
    Stores educational qualifications of an HR applicant.
    Each record includes the degree, institution, and duration.
    """
    _name = "hr.applicant.education"
    _description = "Education for Applicants"
    _order = "degree_duration DESC"

    applicant_id = fields.Many2one(
        "hr.applicant", string="Applicant", required=True, ondelete="cascade"
    )
    degree = fields.Char(string="Degree", required=True)
    institution = fields.Char(string="Institution", required=True)
    degree_duration = fields.Char(string="Duration", required=True)


class HrApplicant(models.Model):
    """
    Inherits from the base HR applicant model to add extra fields
    and behavior, including resume analysis, education, work history,
    and integration with a resume parser.
    """
    _inherit = "hr.applicant"

    name = fields.Char(required=False, index=True)
    candidate_id = fields.Many2one(
        "hr.applicant",
        required=False,
        index=True,
    )
    job_id = fields.Many2one("hr.job", required=False)
    partner_name = fields.Char(required=False, index=True)
    work_experience_ids = fields.One2many(
        "hr.applicant.work.experience", "applicant_id", string="Work Experience"
    )
    education_ids = fields.One2many(
        "hr.applicant.education", "applicant_id", string="Education"
    )
    resume_relevance_score_r = fields.Float(
        string="Resume Relevance Score", widget="progressbar"
    )
    resume_sentiment = fields.Html(string="Sentiment Analysis")
    total_work_experience = fields.Char(
        string="Total Work Experience", store=True, readonly=True
    )
    allow_parser = fields.Boolean(
        string="Allow Resume Parser",
        # default=lambda self: self.env.company.resume_scanner,
    )
    sentiment_json_data = fields.Json(string="Resume Sentiment JSON")
    sentiment_data = fields.Char(string="Sentiment Data")

    # === AI Analysis Fields ===
    analysis_status = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Done'),
        ('error', 'Error')
    ], string="Analysis Status", default='pending')

    communication_style_color = fields.Char("Communication Style Color", default="#4285F4")
    cultural_alignment_color = fields.Char("Cultural Alignment Color", default="#4285F4")
    drive_color = fields.Char("Drive Level Color", default="#00C851")
    risk_color = fields.Char("Risk Assessment Color", default="#FF8A00")

    # Sentiment
    sentiment_score = fields.Integer("Sentiment Score")
    emotional_tone = fields.Char("Emotional Tone")
    sentiment_color = fields.Char("Sentiment Color")

    # Confidence
    confidence_score = fields.Integer("Confidence Score")

    # Communication
    communication_style = fields.Char("Communication Style")

    # Cultural Fit
    cultural_fit_score = fields.Integer("Cultural Fit Score")
    cultural_alignment = fields.Char("Cultural Alignment")

    # Motivation
    motivation_score = fields.Integer("Motivation Score")
    drive_level = fields.Char("Drive Level")
    personality_traits = fields.Text("Key Personality Traits")  # or Json if you want array

    # Red Flags
    risk_assessment = fields.Char("Risk Assessment")
    red_flags_count = fields.Integer("Red Flags Count")

    # Final Scores
    resume_relevance_score = fields.Integer("Resume Relevance")
    hire_recommendation_score = fields.Integer("Hire Recommendation Score")

    # Raw JSON (optional, for debugging)
    resume_analysis_json = fields.Json("Full Analysis JSON")

    confidence_indicators = fields.Text("Confidence Indicators")
    areas_for_improvement = fields.Text("Areas for Improvement")
    communication_strengths = fields.Text("Communication Strengths")
    areas_for_development = fields.Text("Areas for Development")
    cultural_values = fields.Text("Cultural Values")
    collaboration_indicators = fields.Text("Collaboration Indicators")
    primary_motivators = fields.Text("Primary Motivators")
    red_flags_detected = fields.Text("Red Flags")
    positive_indicators = fields.Text("Positive Indicators")


    @api.model
    def run_resume_analysis(self, applicant_id):
        applicant = self.browse(applicant_id)
        if not applicant.exists():
            return {"success": False, "message": "Applicant not found"}

        auth_key = self.env["ir.config_parameter"].sudo().get_param(
            "wb_scandoc_integration.scandoc_auth_key"
        )
        if not auth_key:
            raise ValidationError("Auth key missing")
            # return {"success": False, "message": "Auth key missing"}

        data = applicant.sentiment_data
        if not data:
            return {"success": False, "message": "No sentiment_data"}

        if not applicant.job_id:
            raise ValidationError("Please set jobposition")

        company = self.env.company
        if company.remaining_analysis_scan <= 0:
            return {"success": False, "message": "Your analysis credits have expired. Please purchase additional credits or upgrade your plan."}
            # raise ValidationError("Please purchase a scan limit.")

        payload = {
            "resume_text": json.dumps(data, indent=2, ensure_ascii=False),
            "job_description": applicant.job_id.description or "",
            "company_profile": applicant.job_id.company_id.name or "",
        }

        headers = {
            "Authorization": f"Bearer {auth_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        url = "https://scandocapi--scandoc-api.us-central1.hosted.app/analyze-resume-stream"

        try:
            with requests.post(url, headers=headers, json=payload, stream=True, timeout=180) as r:
                r.raise_for_status()
                full_analysis = None
                event = None

                for line in r.iter_lines(decode_unicode=True):
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:") and event == "complete":
                        try:
                            obj = json.loads(line[5:].strip())
                            full_analysis = obj.get("fullAnalysis")
                        except:
                            continue
                        break

                if not full_analysis:
                    applicant.write({"analysis_status": "error"})
                    return {"success": False, "message": "No fullAnalysis"}

                # === EXTRACT & SAVE SCORES ===
                s = full_analysis.get("sentiment_behavioral_intelligence", {})
                c = full_analysis.get("confidence_level_analysis", {})
                com = full_analysis.get("communication_style_profiling", {})
                cult = full_analysis.get("cultural_fit_indicators", {})
                mot = full_analysis.get("motivation_analysis", {})
                red = full_analysis.get("red_flag_detection", {})
                final = full_analysis.get("overall_scores", {})
                vals = {
                    "communication_style_color": com.get("primary_style_color") or "#4285F4",
                    "cultural_alignment_color": cult.get("cultural_alignment_color") or "#4285F4",
                    "drive_color": mot.get("drive_level_color") or "#00C851",
                    "risk_color": red.get("risk_assessment_color") or "#FF8A00",
                    "analysis_status": "done",
                    "resume_analysis_json": full_analysis,

                    "confidence_indicators": ", ".join(c.get("confidence_indicators", [])) or "—",
                    "areas_for_improvement": ", ".join(c.get("areas_for_improvement", [])) or "—",
                    "communication_strengths": ", ".join(com.get("communication_strengths", [])) or "—",
                    "areas_for_development": ", ".join(com.get("areas_for_development", [])) or "—",
                    "cultural_values": ", ".join(cult.get("cultural_values", [])) or "—",
                    "collaboration_indicators": ", ".join(cult.get("collaboration_indicators", [])) or "—",
                    "primary_motivators": ", ".join(mot.get("primary_motivators", [])) or "—",
                    "red_flags_detected": ", ".join(red.get("red_flags_detected", [])) or "—",
                    "positive_indicators": ", ".join(red.get("positive_indicators", [])) or "—",

                    # === SAFE DEFAULTS ===
                    "sentiment_score": s.get("overall_sentiment_score") or 0,
                    "emotional_tone": s.get("emotional_tone") or "—",
                    "sentiment_color": s.get("overall_sentiment_color") or "#2BBBAD",

                    "confidence_score": c.get("overall_confidence_score") or 0,
                    "communication_style": com.get("primary_style") or "—",
                    "cultural_fit_score": cult.get("fit_score") or 0,
                    "cultural_alignment": cult.get("cultural_alignment") or "—",
                    "motivation_score": mot.get("motivation_score") or 0,
                    "drive_level": mot.get("drive_level") or "—",
                    "risk_assessment": red.get("risk_assessment") or "—",
                    "red_flags_count": len(red.get("red_flags_detected", [])),
                    "resume_relevance_score_r": final.get("resume_relevance_score") or 0,
                    "hire_recommendation_score": final.get("hire_recommendation_score") or 0,
                    "personality_traits": ", ".join(s.get("key_personality_traits", [])) or "—",
                }

                applicant.write(vals)
                return {"success": True, "data": vals}

        except Exception as e:
            applicant.write({"analysis_status": "error"})
            return {"success": False, "message": str(e)}

    @staticmethod
    def extract_start_year(duration):
        """
        Extracts the start year from a given duration string (e.g., "2018 - 2022").
        Returns 0 if parsing fails.
        """
        parts = duration.split("-")
        return int(parts[0].strip()) if parts and parts[0].strip().isdigit() else 0

    def action_open_resume_analysis(self):
        """Open the ScanDoc Resume Analysis Dashboard"""
        self.ensure_one()
        auth_key = self.env["ir.config_parameter"].sudo().get_param(
            "wb_scandoc_integration.scandoc_auth_key"
        )
        if not auth_key:
            raise ValidationError("Auth key missing")
        if not self.job_id:
            raise ValidationError("Select Job Position")

        action = self.env.ref('wb_scandoc_integration.action_sentiment_dashboard').read()[0]
        
        # CRITICAL: Pass applicant_id in context AND params
        context = {
            'applicant_id': self.id,
            'active_id': self.id,
            'active_model': 'hr.applicant',
        }
        
        action.update({
            'context': context,
            'params': {'applicant_id': self.id},  # Also pass in params
        })
        
        return action

    def _normalize_sentiment_payload(self, api_response):
        """Convert API response into a simplified dict for HTML rendering."""

        sentiment_raw = api_response.get("sentiment_analysis", {})
        tone_raw = api_response.get("tone_detection", {})

        sentiment_data = {
            "Polarity Score": sentiment_raw.get("polarity_score"),
            "Subjectivity Score": sentiment_raw.get("subjectivity_score"),
            "Justification": sentiment_raw.get("justification"),
            "Work Stability Check": {
                "Risk Level": sentiment_raw.get("work_stability_check", {}).get("risk_level"),
                "Job Changes in Last 6 Months": sentiment_raw.get("work_stability_check", {}).get("job_changes_last_6_months"),
                "Job Changes in Last 1 Year": sentiment_raw.get("work_stability_check", {}).get("job_changes_last_1_year"),
                "Average Tenure per Company": sentiment_raw.get("work_stability_check", {}).get("average_tenure_per_company"),
                "Stability Assessment": sentiment_raw.get("work_stability_check", {}).get("stability_assessment"),
            }
        }

        # Tone mapping
        tone_data = {}
        for tone, details in tone_raw.items():
            tone_data[tone.title()] = {
                "Keyword Count": details.get("keyword_count"),
                "Interpretation": details.get("interpretation"),
            }

        return sentiment_data, tone_data
        return action
    

    def action_parse_cv(self):
        """
        Button action to send stored sentiment_json_data to ScanDoc API
        and fetch parsed response.
        """
        self.ensure_one()

        # 🔑 Auth Key
        auth_key = self.env['ir.config_parameter'].sudo().get_param(
            'wb_scandoc_integration.scandoc_auth_key'
        )
        if not auth_key:
            raise UserError(_("Missing ScanDoc authentication key in system parameters."))

        if not self.sentiment_json_data:
            raise UserError(_("No sentiment data available to send."))

        # ✅ API Endpoint (adjust if needed)
        # url = "https://scandocapi--scandoc-api.us-central1.hosted.app/analyze-resume-stream"
        url = "https://scandocapi--scandoc-api.us-central1.hosted.app/analyze-resume-stream?authKey=" + str(auth_key)

        # ✅ Build JSON payload
        payload = { 
            "data": json.loads(self.sentiment_json_data) if isinstance(self.sentiment_json_data, str) else self.sentiment_json_data,
        }

        resume_sentiment_data = []
        try:
            # Stream response
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                stream=True,  # important for SSE
            )
            # response.raise_for_status()

            final_result = None

            for line in response.iter_lines():
                if not line:
                    continue
                decoded_line = line.decode("utf-8")
                if decoded_line.startswith("data:"):
                    raw_data = decoded_line.lstrip("data: ").strip()
                    try:
                        event_data = json.loads(raw_data)
                        # Store only sentiment_analysis section
                        if event_data.get("data"):
                            final_result = event_data["data"]
                            if final_result:
                                sentiment_data, tone_data = self._normalize_sentiment_payload(final_result)
                                resume_sentiment_data.append(final_result)
                    except json.JSONDecodeError:
                        _logger.warning("Non-JSON SSE line: %s", raw_data)

        except requests.exceptions.RequestException as e:
            raise UserError(f"ScanDoc API request failed: {e}")
        if resume_sentiment_data:
            sentiment_html = self._build_sentiment_html(resume_sentiment_data)
            self.resume_sentiment = sentiment_html


    def generate_sentiment_visual(self, sentiment_score):
        """
        Generate an emoji and label representation for a given sentiment score.

        :param sentiment_score: The sentiment score as an integer.
        :return: A string with visual (emoji) feedback.
        """
        sentiment_score = sentiment_score * 100 if sentiment_score else 0
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

    def _build_sentiment_html(self, final_data):
        """
        Builds a styled HTML block for the candidate analysis.

        :param final_data: List of dictionaries containing sentiment, confidence, communication, motivation, red flags, tone, predictive analytics.
        :return: HTML string
        """
        html = """
        <div style="max-width: 800px; margin: auto; background: rgba(0,0,0,0.05);
                    padding: 24px; border-radius: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
            <h1 style="text-align:center; color:#222;">Candidate Analysis</h1>
        """

        # 1️⃣ Sentiment & Behavioral Intelligence
        sentiment_section = final_data[0].get('sentiment_behavioral_intelligence', {})
        if sentiment_section:
            html += f"""
            <div style="border:1px solid #eee; border-radius:12px; padding:16px; margin-bottom:24px; background:#f9f9f9;">
                <h2>Sentiment & Behavioral Intelligence</h2>
                <p><strong>Overall Sentiment Score:</strong> {sentiment_section.get('overall_sentiment_score')}</p>
                <p><strong>Emotional Tone:</strong> {sentiment_section.get('emotional_tone')}</p>
                <p><strong>Key Traits:</strong> {', '.join(sentiment_section.get('key_personality_traits', []))}</p>
                <h4>Behavioral Patterns:</h4>
            """
            for pattern, details in sentiment_section.get('behavioral_patterns', {}).items():
                html += f"<p><strong>{pattern.replace('_',' ').title()}:</strong> {details.get('evidence')} (Strength: {details.get('strength')})</p>"
            html += "</div>"

        # 2️⃣ Confidence Level Analysis
        confidence_section = final_data[1].get('confidence_level_analysis', {})
        if confidence_section:
            html += f"""
            <div style="border:1px solid #eee; border-radius:12px; padding:16px; margin-bottom:24px; background:#f0f9f0;">
                <h2>Confidence Level Analysis</h2>
                <p><strong>Overall Confidence Score:</strong> {confidence_section.get('overall_confidence_score')}</p>
                <h4>Breakdown:</h4>
            """
            for key, details in confidence_section.get('confidence_breakdown', {}).items():
                html += f"<p><strong>{key.replace('_',' ').title()}:</strong> {details.get('analysis')} (Score: {details.get('score')}, Color: {details.get('color')})</p>"
            html += f"<p><strong>Indicators:</strong> {', '.join(confidence_section.get('confidence_indicators', []))}</p>"
            html += "</div>"

        # 3️⃣ Communication Style Profiling
        communication_section = final_data[2].get('communication_style_profiling', {})
        if communication_section:
            html += f"""
            <div style="border:1px solid #eee; border-radius:12px; padding:16px; margin-bottom:24px; background:#f9f9f9;">
                <h2>Communication Style</h2>
                <p><strong>Primary Style:</strong> {communication_section.get('primary_style')}</p>
                <h4>Assessment:</h4>
            """
            for key, details in communication_section.get('communication_assessment', {}).items():
                html += f"<p><strong>{key.replace('_',' ').title()}:</strong> {details.get('analysis')} (Score: {details.get('score')})</p>"
            html += "</div>"

        # 4️⃣ Motivation Analysis
        motivation_section = final_data[3].get('motivation_analysis', {})
        if motivation_section:
            html += f"""
            <div style="border:1px solid #eee; border-radius:12px; padding:16px; margin-bottom:24px; background:#f0f9f0;">
                <h2>Motivation Analysis</h2>
                <p><strong>Drive Level:</strong> {motivation_section.get('drive_level')}</p>
                <p><strong>Motivation Score:</strong> {motivation_section.get('motivation_score')}</p>
                <h4>Breakdown:</h4>
            """
            for key, details in motivation_section.get('motivation_breakdown', {}).items():
                html += f"<p><strong>{key.replace('_',' ').title()}:</strong> {details.get('analysis')} (Score: {details.get('score')})</p>"
            html += f"<p><strong>Primary Motivators:</strong> {', '.join(motivation_section.get('primary_motivators', []))}</p>"
            html += "</div>"

        # 5️⃣ Red Flag Detection
        red_flag_section = final_data[4].get('red_flag_detection', {})
        if red_flag_section:
            html += f"""
            <div style="border:1px solid #eee; border-radius:12px; padding:16px; margin-bottom:24px; background:#fff5e6;">
                <h2>Red Flag Detection</h2>
                <p><strong>Risk Assessment:</strong> {red_flag_section.get('risk_assessment')}</p>
                <p><strong>Red Flags:</strong> {', '.join(red_flag_section.get('red_flags_detected', []))}</p>
                <p><strong>Positive Indicators:</strong> {', '.join(red_flag_section.get('positive_indicators', []))}</p>
            </div>
            """

        # 6️⃣ Tone Detection
        tone_section = final_data[4].get('tone_detection', {})
        if tone_section:
            html += """
            <div style="border:1px solid #eee; border-radius:12px; padding:16px; margin-bottom:24px; background:#f9f9f9;">
                <h2>Tone Detection</h2>
                <table style="width:100%; border-collapse: collapse;">
            """
            emoji_map = {
                'leadership': '🎯', 'managerial': '👨‍💼', 'individual_contributions': '🧍',
                'confidence': '🔒', 'problem_solving': '🧩', 'communication': '💬', 'technical': '🛠️'
            }
            for key, details in tone_section.items():
                emoji = emoji_map.get(key.lower(), '')
                html += f"<tr><td>{emoji} <strong>{key.title()}</strong></td><td style='text-align:right;'>{details.get('keyword_count')}</td></tr>"
            html += "</table></div>"

        html += "</div>"  # main container
        return html
