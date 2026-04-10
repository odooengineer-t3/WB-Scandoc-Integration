from odoo import http
from odoo.http import request
import requests
import json
import logging
from dateutil import parser
from datetime import timezone
import pytz
from pytz import timezone
from datetime import datetime

_logger = logging.getLogger(__name__)


class ScanDocController(http.Controller):
    @http.route("/wb_odoo_dynamic_dashboard/verify_auth_key", type="json", auth="user", csrf=False)
    def verify_auth_key(self, **kwargs):
        auth_key = kwargs.get("auth_key")
        company = request.env.company.sudo()
        if not auth_key:
            return {"status": "error", "message": "Authorization key not provided."}
        try:
            settings = request.env["res.config.settings"].sudo().create({
                "scandoc_auth_key": auth_key,
            })
            result = settings.action_verify_auth_key()
            if isinstance(result, dict) and result.get("type") == "ir.actions.client":
                company.write({"scandoc_auth_key": auth_key})
                request.env.cr.commit()         # <-- important
                return {"status": "success", "message": "Key verified and saved!"}
            return {"status": "error", "message": "Invalid key."}
        except Exception as e:
            request.env.cr.rollback()
            return {"status": "error", "message": str(e)}

    # ✅ Discard auth key
    @http.route("/wb_odoo_dynamic_dashboard/discard_auth_key", type="json", auth="user")
    def discard_auth_key(self, **kwargs):
        company = request.env.company
        company.scandoc_auth_key = False  # clear from company
        company.used_credit = False
        company.scans_limit = False
        company.remaining_credit = False
        company.transaction_ids = False
        company.audit_history_ids = False
        params = request.env['ir.config_parameter'].sudo().search([
        ('key', '=', 'wb_scandoc_integration.scandoc_auth_key')
        ])
        if params:
            params.unlink()
        else:
            request.env['ir.config_parameter'].sudo().set_param('wb_scandoc_integration.scandoc_auth_key', '')

        # Also clear from res.config.settings
        settings = request.env["res.config.settings"].create({
            "scandoc_auth_key": False,
        })

        return {"status": "success", "message": "Auth key discarded"}

    @http.route("/wb_odoo_dynamic_dashboard/reset_session", type="json", auth="user")
    def reset_session(self):
        # lightweight route to reset DB transaction
        self.env.cr.rollback()
        return {"success": True}

    # ✅ Reconfigure auth key
    @http.route("/wb_odoo_dynamic_dashboard/reconfigure_auth_key", type="json", auth="user")
    def reconfigure_auth_key(self, **kwargs):
        company = request.env.company
        company.scandoc_auth_key = False  # clear from company

        # Also clear from res.config.settings
        request.env["res.config.settings"].create({
            "scandoc_auth_key": False,
        })

        return {"status": "success", "message": "Auth key reconfigured"}

    @http.route("/wb_odoo_dynamic_dashboard/check_auth_status", type="json", auth="user")
    def check_auth_status(self):
        """Return current authorization status."""
        company = request.env.company.sudo()
        key = company.scandoc_auth_key
        return {
            "is_verified": bool(key),
            "auth_key": key or "",
            "message": "Key verified." if key else "No key found.",
        }


    @http.route('/wb_odoo_dynamic_dashboard/get_credit_info', type='json', auth='user')
    def get_credit_info(self, force_refresh=False):
        company = request.env.user.company_id
        auth_key = company.scandoc_auth_key

        # ============================================================
        # ✅ STEP 1: UPDATE CREDIT & ANALYSIS COUNTS (validate-auth API)
        # ============================================================
        if auth_key:
            try:
                validate_url = "https://scandocapi--scandoc-api.us-central1.hosted.app/api/documents/validate-auth"
                validate_resp = requests.post(validate_url, json={"authKey": auth_key}, timeout=10)

                if validate_resp.status_code == 200:
                    user_data = validate_resp.json().get("user", {})

                    scans_used = user_data.get("scansUsed", 0)
                    scans_limit = user_data.get("scansLimit", 0)
                    remaining = max(scans_limit - scans_used, 0)
                    analysis_scan_limit = user_data.get('analysisScansLimit')
                    company.sudo().write({
                        "scans_limit": scans_limit + scans_used,
                        "used_credit": scans_used,
                        "remaining_credit": scans_limit,
                        "remaining_analysis_scan":analysis_scan_limit
                    })

            except Exception as e:
                _logger.error("Credit update failed: %s", e)

        if auth_key:
            try:
                api_url = "https://scandocapi--scandoc-api.us-central1.hosted.app/api/history/scan"
                headers = {"Authorization": f"Bearer {auth_key}"}
                response = requests.get(api_url, headers=headers, timeout=15)
                response.raise_for_status()
                api_data = response.json()
                audit_records = api_data.get("data", [])
                if audit_records:
                    for item in audit_records:
                        doc_id = item.get("id")
                        doc_name = item.get("fileName")
                        audit_date = item.get("createdAt")
                        status = item.get("status")
                        # processed_date = parser.parse(audit_date).astimezone(timezone.utc).replace(tzinfo=None)
                        dt_raw = parser.parse(audit_date)  # API timestamp (UTC)
                        ist_time = dt_raw.astimezone(timezone("Asia/Kolkata"))  # Convert to IST
                        processed_date = ist_time.replace(tzinfo=None)
                        existing = request.env["audit.history"].sudo().search([
                            ("document_id", "=", doc_id)
                        ], limit=1)

                        if not existing:
                            history = request.env["audit.history"].sudo().create({
                                "company_id": company.id,
                                "document_name": doc_name,
                                "status": status,
                                "auditlog_date": processed_date,
                            })
                            _logger.info("✅ Created new record ID %s for %s", history.id, doc_name)
                        else:
                            _logger.info("ℹ️ Skipped existing document %s", doc_name)

            except Exception as e:
                _logger.error("Failed to sync ScanDoc API: %s", e)

        # ✅ Always return updated data to the dashboard
        return {
            "scans_limit": company.scans_limit,
            "authKey": company.scandoc_auth_key,
            "used_credit": company.used_credit,
            "remaining_credit": company.remaining_credit,
            "transaction_data": [
                {
                    "invoice_name": t.invoice_name,
                    "status": t.status,
                    "purchase_date": t.purchase_date_transaction.strftime('%Y-%m-%d %H:%M:%S') if t.purchase_date_transaction else '',
                    "quantity": t.quantity,
                    "total": t.total,
                    "id": t.id
                }
                for t in company.transaction_ids
            ],
            "history_data": [
                {
                    "id": t.id,
                    "document_name": t.document_name,
                    "status": t.status,
                    "auditlog_date": t.auditlog_date,
                    "document_id":t.document_id,
                }
                for t in company.audit_history_ids
            ],
        }

    @http.route('/scandoc/login', type='json', auth='public', methods=['POST'], csrf=False)
    def scandoc_login(self, **kwargs):
        username = (kwargs.get('username') or '').strip().lower()
        password = kwargs.get('password')

        if not username or not password:
            return {'success': False, 'message': 'Username and password are required.'}

        url = "https://scandocstage--scandoc-7c231.us-east4.hosted.app/api/auth-login"
        payload = {"email": username, "password": password}
        headers = {"Content-Type": "application/json"}

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
        except requests.RequestException as exc:
            _logger.warning("ScanDoc connection error: %s", exc)
            return {'success': False, 'message': 'Connection error. Please try again.'}

        # ------------------------------------------------------------------
        # 1. HTTP-level failure (5xx, 4xx other than 200)
        # ------------------------------------------------------------------
        if resp.status_code != 200:
            _logger.info("ScanDoc returned HTTP %s: %s", resp.status_code, resp.text)
            return {
                'success': False,
                'message': resp.json().get('message') or 'Invalid Credential.'
            }

        # ------------------------------------------------------------------
        # 2. Parse JSON – protect against malformed body
        # ------------------------------------------------------------------
        try:
            data = resp.json()
        except ValueError:
            _logger.warning("ScanDoc returned non-JSON: %s", resp.text)
            return {'success': False, 'message': 'Invalid response from credential server.'}

        # ------------------------------------------------------------------
        # 3. Business-level failure (wrong credentials, account locked, …)
        # ------------------------------------------------------------------
        if not data.get('success'):
            # Use the exact message the remote service gave us
            remote_msg = 'Invalid credential'
            return {'success': False, 'message': remote_msg}

        # ------------------------------------------------------------------
        # 4. Success – now we *must* have an authKey
        # ------------------------------------------------------------------
        if resp.status_code == 200:
            auth_key = data.get('data', {}).get('user', {}).get('authKey')
            if not auth_key:
                _logger.error(
                    "Invalid Credential! ScanDoc login succeeded but authKey missing! Payload: %s",
                    json.dumps(data, indent=2)
                )
                return {
                    'success': False,
                    'message': 'Invalid Credential! Auth key not returned by ScanDoc. Contact support.'
                }

        # ------------------------------------------------------------------
        # 5. Everything OK
        # ------------------------------------------------------------------
        return {
            'success': True,
            'token': data.get('token'),
            'authKey': auth_key,
            'message': 'Login successful'
        }


    @http.route('/scandoc/get_auth_key', type='json', auth='user')
    def get_scandoc_auth_key(self):
        company = request.env.company
        return {
            'success': True,
            'authKey': company.sudo().scandoc_auth_key or ''
        }