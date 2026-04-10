from odoo import api, SUPERUSER_ID

def post_init_hook(env):
    """
       Post-init hook for wb_scandoc_integration.
       Automatically installs related submodules if available.
       Runs only once after initial installation.
       """
    module_names = [
        "wb_scandoc_purchase",
        "wb_scandoc_inventory",
        "wb_scandoc_hr_recruitment",
        "wb_odoo_dynamic_dashboard",
    ]
    for module_name in module_names:
        module = env["ir.module.module"].search([("name", "=", module_name)], limit=1)
        if not module:
            continue
        else:
            module.button_install()
    
    # Check and grant initial ScanDoc access based on existing auth key
    try:
        config_settings = env['res.config.settings']
        config_settings._check_and_grant_initial_access()
    except Exception as e:
        # Log error but don't break installation
        import logging
        _logger = logging.getLogger(__name__)
        _logger.error("Failed to check initial ScanDoc access in post_init_hook: %s", str(e))
