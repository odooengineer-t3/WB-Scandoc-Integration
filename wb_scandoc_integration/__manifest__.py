# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) Wan Buffer Services (<https://wanbuffer.com/>).
#
#    For Module Support : support@wanbuffer.com  or Call : +91 9638442270
#
##############################################################################
{
    "name": "ScanDoc Integration",
    'author': 'Wan Buffer Services',
    'maintainer': 'Wan Buffer Services',
    "license": "OPL-1",
    "website": "https://wanbuffer.com",
    "support": "support@wanbuffer.com",
    "version": "19.0.1.0.0",

    "category": "Document Management/OCR",

    "summary": """Production-ready document scanning and processing with advanced OCR, currency handling, 
                  and automated data extraction. Supports multiple document types with robust error handling.""",

    "description": """
    **ScanDoc Integration - Production Ready Module**
    
    Advanced document processing solution with enterprise-grade features:
    
    **Core Features:**
    • OCR processing for invoices, receipts, and documents
    • Automatic currency detection and activation
    • Purchase order creation from vendor bills
    • HR resume parsing and skill extraction
    • Stock picking document processing
    
    **Production Features:**
    • Comprehensive error handling and logging
    • Input validation and security checks
    • Configurable processing parameters
    • Multi-currency support with auto-activation
    • Batch processing capabilities
    
    **Security & Performance:**
    • File type validation and size limits
    • SQL injection protection
    • Optimized database queries
    • Structured logging system
    • Graceful error recovery
    
    **Requirements:**
    • Python packages: requests, openpyxl, pytesseract, PyPDF2, Pillow
    • System dependencies: tesseract-ocr
    • ScanDoc API credentials (configured via Settings)
    """,

    "depends": [
        'base', 
        'base_setup', 
        'mail',
        'purchase', 
        'stock', 
        'hr',
        'hr_recruitment', 
        'hr_skills',
        'web',
        'crm'
    ],

    "data": [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/scandoc_sequence.xml',
        'data/system_parameters.xml',
        'data/cron_crm_lead.xml',
        'wizards/resume_parser_wizard_views.xml',
        'views/scandoc_auth_action.xml',
        'views/menu_views.xml',
        'views/dashboard_views.xml',
        'views/scandoc_manager_views.xml',
        'views/res_config_settings.xml',
        'views/hr_applicant_views.xml',
        'views/stock_picking_views.xml',
        'views/purchase_order_views.xml',
    ],
    'external_dependencies': {
        'python': [
            'requests', 
            'openpyxl', 
            'pytesseract', 
            'PyPDF2', 
            'Pillow', 
            'python-dateutil',
            'pdfminer.six'
        ], 
        'bin': ['tesseract']
    },

    'demo': [],
    'qweb': [],
    
    # Production settings
    'installable': True,
    'auto_install': False,
    'application': True,
    'bootstrap': False,
    
    # Marketplace info
    "images": ["static/description/background.png"],
    "price": 0,
    "currency": "EUR",
    
    # Development info
    'development_status': 'Production/Stable',
    'technical_name': 'wb_scandoc_integration',
    'assets': {
        'web.assets_backend': [
            'wb_scandoc_integration/static/src/js/dynamic_dashboard.js',
            'wb_scandoc_integration/static/src/js/sentiment_dashboard.js',
            'wb_scandoc_integration/static/src/xml/dynamic_dashboard_template.xml',
            'wb_scandoc_integration/static/src/xml/sentiment_dashboard_template.xml',
            'wb_scandoc_integration/static/src/scss/sentiment_dashboard.scss'
        ],
    },
}
