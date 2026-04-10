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
Production Configuration Helper for ScanDoc Integration

This module provides helper methods to manage system parameters
and configuration settings in a production environment.
"""

import logging
from odoo import models, api

_logger = logging.getLogger(__name__)


class ScanDocConfigHelper(models.AbstractModel):
    """Helper class for managing ScanDoc configuration parameters"""
    _name = 'scandoc.config.helper'
    _description = 'ScanDoc Configuration Helper'

    @api.model
    def get_config_value(self, key, default=None, convert_type=None):
        """
        Safely get configuration value from system parameters
        
        :param key: Configuration key (without module prefix)
        :param default: Default value if parameter not found
        :param convert_type: Type to convert to ('int', 'float', 'bool')
        :return: Configuration value
        """
        try:
            full_key = f'wb_scandoc_integration.{key}'
            value = self.env['ir.config_parameter'].sudo().get_param(full_key, default)
            
            if value is None:
                return default
                
            # Type conversion
            if convert_type == 'int':
                return int(value)
            elif convert_type == 'float':
                return float(value)
            elif convert_type == 'bool':
                return str(value).lower() in ('true', '1', 'yes', 'on')
            
            return value
            
        except Exception as e:
            _logger.warning("Failed to get config value for %s: %s", key, str(e))
            return default
    
    @api.model
    def set_config_value(self, key, value):
        """
        Safely set configuration value in system parameters
        
        :param key: Configuration key (without module prefix)
        :param value: Value to set
        :return: True if successful, False otherwise
        """
        try:
            full_key = f'wb_scandoc_integration.{key}'
            self.env['ir.config_parameter'].sudo().set_param(full_key, str(value))
            return True
        except Exception as e:
            _logger.error("Failed to set config value for %s: %s", key, str(e))
            return False
    
    @api.model
    def get_scandoc_auth_key(self):
        """Get ScanDoc API authentication key"""
        return self.get_config_value('scandoc_auth_key')
    
    @api.model
    def get_api_url(self):
        """Get ScanDoc API URL"""
        return self.get_config_value(
            'scandoc_api_url',
            'https://scandocapi--scandoc-api.us-central1.hosted.app/api/documents/scan'
        )
    
    @api.model
    def get_api_timeout(self):
        """Get API timeout in seconds"""
        return self.get_config_value('scandoc_api_timeout', 120, 'int')
    
    @api.model
    def get_max_retries(self):
        """Get maximum number of API retries"""
        return self.get_config_value('scandoc_max_retries', 2, 'int')
    
    @api.model
    def get_max_file_size_mb(self):
        """Get maximum file size in MB"""
        return self.get_config_value('max_file_size_mb', 50, 'int')
    
    @api.model
    def get_allowed_extensions(self):
        """Get list of allowed file extensions"""
        extensions_str = self.get_config_value(
            'allowed_file_extensions',
            '.pdf,.png,.jpg,.jpeg,.tiff,.bmp,.docx,.xlsx'
        )
        return [ext.strip() for ext in extensions_str.split(',')]
    
    @api.model
    def is_file_validation_enabled(self):
        """Check if file validation is enabled"""
        return self.get_config_value('enable_file_validation', True, 'bool')
    
    @api.model
    def is_auto_currency_activation_enabled(self):
        """Check if auto currency activation is enabled"""
        return self.get_config_value('auto_activate_currencies', True, 'bool')
    
    @api.model
    def is_debug_logging_enabled(self):
        """Check if debug logging is enabled"""
        return self.get_config_value('enable_debug_logging', False, 'bool')
    
    @api.model
    def is_audit_logging_enabled(self):
        """Check if audit logging is enabled"""
        return self.get_config_value('enable_audit_logging', True, 'bool')
    
    @api.model
    def get_tesseract_config(self):
        """Get Tesseract OCR configuration"""
        return self.get_config_value(
            'tesseract_config',
            '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,!@#$%^&*()_+-=[]{}|;:,.<>?/~` '
        )
    
    @api.model
    def validate_configuration(self):
        """
        Validate all configuration parameters
        
        :return: Dict with validation results
        """
        validation_results = {
            'is_valid': True,
            'errors': [],
            'warnings': []
        }
        
        try:
            # Check required parameters
            auth_key = self.get_scandoc_auth_key()
            if not auth_key:
                validation_results['errors'].append('ScanDoc API key not configured')
                validation_results['is_valid'] = False
            
            # Check API URL
            api_url = self.get_api_url()
            if not api_url or not api_url.startswith('https://'):
                validation_results['warnings'].append('API URL should use HTTPS')
            
            # Check timeout values
            timeout = self.get_api_timeout()
            if timeout < 30 or timeout > 300:
                validation_results['warnings'].append('API timeout should be between 30-300 seconds')
            
            # Check file size limits
            max_size = self.get_max_file_size_mb()
            if max_size > 100:
                validation_results['warnings'].append('Large file size limit may impact performance')
            
            # Check retry settings
            retries = self.get_max_retries()
            if retries > 5:
                validation_results['warnings'].append('High retry count may cause delays')
            
        except Exception as e:
            validation_results['errors'].append(f'Configuration validation failed: {str(e)}')
            validation_results['is_valid'] = False
        
        return validation_results
    
    @api.model
    def get_production_checklist(self):
        """
        Get production deployment checklist
        
        :return: Dict with checklist items and their status
        """
        checklist = {}
        
        try:
            # API Configuration
            checklist['api_key_configured'] = bool(self.get_scandoc_auth_key())
            checklist['https_enabled'] = self.get_api_url().startswith('https://')
            
            # Security Settings
            checklist['file_validation_enabled'] = self.is_file_validation_enabled()
            checklist['audit_logging_enabled'] = self.is_audit_logging_enabled()
            
            # Performance Settings
            checklist['reasonable_timeout'] = 30 <= self.get_api_timeout() <= 300
            checklist['reasonable_file_size'] = self.get_max_file_size_mb() <= 100
            
            # Debug Settings (should be disabled in production)
            checklist['debug_logging_disabled'] = not self.is_debug_logging_enabled()
            
        except Exception as e:
            _logger.error("Failed to generate production checklist: %s", str(e))
            checklist['error'] = str(e)
        
        return checklist