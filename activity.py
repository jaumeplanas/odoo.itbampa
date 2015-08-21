# -*- coding: utf-8 -*-

from openerp import models, fields, api, _
# from openerp.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta

class ActivityType(models.Model):
    _name = 'itbampa.activity.type'
    
    name = fields.Char("Activity Type", required=True)
    
class ActivityEventPartner(models.Model):
    _name = 'itbampa.activity.event.partner'

    activity_id = fields.Many2one('itbampa.activity.event', string="Activity Event", required=True, ondelete='cascade')
    partner_id = fields.Many2one(
            'res.partner', string="Member", domain="[('ampa_partner_type', 'in', ['tutor', 'student'])]", required=True, ondelete='cascade')
    partner_current_course = fields.Selection(related="partner_id.current_course", string="Current Course")
    comment = fields.Char(string="Comment")
    activity_product_id = fields.Many2one('product.product', string="Product", required=True, ondelete='cascade')
    # For graph view
    date_start = fields.Date(string="Date Start", related='activity_id.date_start', store=True)
    school_calendar_id = fields.Many2one('itbampa.school.calendar', related='activity_id.school_calendar_id', string="School Calendar", store="True")

class ActivityEvent(models.Model):

    '''Activity Event.'''

    _name = 'itbampa.activity.event'
    _order = 'date_start desc'

    @api.multi
    @api.depends('partner_ids')
    def _compute_total_partners(self):
        for record in self:
            record.total_partners = len(record.partner_ids)  # 

    @api.one
    @api.depends('date_start')
    def _get_name_and_school_calendar(self):
        lang = self._context.get('lang', 'en_US')
        fmt = self.env['res.lang'].search([('code', '=', lang)], limit=1).date_format
        odate = fields.Date().from_string(self.date_start)
        self.name = odate.strftime(fmt)
        ocalendar = self.env['itbampa.school.calendar'].get_school_calendar_from_date(odate)
        self.school_calendar_id = ocalendar

    @api.onchange('date_start')
    def _check_school_calendar_id(self):
        if not self.school_calendar_id:
            return {
                'warning': {
                    'title': _('No School Calendar associated'),
                    'message': _('No School Calendar associated to this date. Please consider to create a new School Calendar that includes this date or to change the date.')
                    }
                }
            

    @api.onchange('activity_type_id')
    def _on_change_activity_type(self):
        self.update_with_registered()
    
    @api.multi
    def update_with_registered(self):
        pids = []
        # Get partner IDs registered
        registered_set = set([x.partner_id.id for x in self.env['itbampa.activity.partner.line'].search([('activity_type_id', '=', self.activity_type_id.id)])])
        # Get partners IDs already defined
        current_set = set([y.partner_id.id for y in self.partner_ids])
        # Get missing partner IDs
        intersect_list = [x for x in list(registered_set - current_set)]
        # If missing
        if len(intersect_list) > 0:
            intersect_objs = self.env['itbampa.activity.partner.line'].search([
                ('activity_type_id', '=', self.activity_type_id.id),
                ('partner_id', 'in', intersect_list)
                ])
            for z in intersect_objs:
                pids.append([0, 0, {'partner_id': z.partner_id.id, 'activity_product_id': z.product_id.id}])
            self.partner_ids = pids
            
    name = fields.Char("Name", compute='_get_name_and_school_calendar', store=True)
    activity_type_id = fields.Many2one('itbampa.activity.type', string="Activity Type", required=True)
    date_start = fields.Date(
            "Start Date", required=True, default=fields.Date.today())
    date_stop = fields.Date("End Date", default=fields.Date.today())
    all_day = fields.Boolean("All Day", default=True)
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    partner_ids = fields.One2many(
            'itbampa.activity.event.partner', 'activity_id', string="Members")
    state = fields.Selection(
            [('open', 'Open'), ('closed', 'Closed'), ('billed', 'Billed')], string="State", default='open')
    total_partners = fields.Integer(
            "Total Registered", compute='_compute_total_partners', store=True)
    school_calendar_id = fields.Many2one('itbampa.school.calendar', string="School Calendar", compute='_get_name_and_school_calendar', store=True)
    
    @api.one
    def action_closed(self):
        self.state = 'closed'

    @api.one
    def action_open(self):
        self.state = 'open'

    @api.one
    def action_billed(self):
        pass

    # When called from code
    # self.signal_workflow('bill_lunch_event')
    
class LunchReportWizard(models.TransientModel):
    """Wizard to select School Calendar for Monthly Activity Attendance"""
    _name = 'itbampa.activity.report.wizard'
    
    def _get_default_school_calendar(self):
        return self.env['itbampa.school.calendar'].search([], limit=1)
    
    @api.onchange('school_calendar_id')
    def _get_month_id(self):
        dtstart = self.school_calendar_id.date_start
        dtend = self.school_calendar_id.date_end
        school_id = self.school_calendar_id.id
        month_obj = self.env['itbampa.activity.report.wizard.month']
        for x in month_obj.search([]):
            x.unlink()
        if (dtstart > '1971-01-01') and (dtend > '1971-01-01'):
            self._cr.execute("""
                SELECT EXTRACT(YEAR from date_start) AS year, EXTRACT(MONTH from date_start) AS month
                FROM itbampa_activity_event
                WHERE date_start BETWEEN %s AND %s
                GROUP BY EXTRACT(YEAR from date_start), EXTRACT(MONTH from date_start)
            """, (dtstart, dtend))
            for x in self._cr.dictfetchall():
                month_obj.create({
                    'year': int(x['year']),
                    'month': int(x['month']),
                    })
        school_obj = self.env['itbampa.school.calendar'].browse(school_id)
        month = month_obj.search([], limit=1)
        self.school_calendar_id = school_obj
        self.month_id = month
                
    @api.one
    @api.depends('month_id')
    def _get_line_ids(self):
        if self.month_id:
            dtstart_o = date(self.month_id.year, self.month_id.month, 1)
            dtend_o = dtstart_o + relativedelta(day=31)
            dtstart = dtstart_o.isoformat()
            dtend = dtend_o.isoformat()
            for line in self.line_ids:
                line.unlink()
            self._cr.execute("""
                SELECT p.name AS partner, t.name_template AS product, count(*) AS total 
                FROM itbampa_activity_event_partner e
                JOIN itbampa_activity_event l ON l.id = e.activity_id
                JOIN res_partner p ON p.id = e.partner_id
                JOIN product_product t ON t.id = e.activity_product_id
                WHERE l.date_start BETWEEN %s AND %s
                GROUP BY p.name, t.name_template
                """, (dtstart, dtend))
            line_obj = zz = self.env['itbampa.activity.report.wizard.line']
        
            for x in self._cr.dictfetchall():
                z = line_obj.create({
                    'partner': x['partner'],
                    'product': x['product'],
                    'total': int(x['total']),
                    })
                zz += z
            self.line_ids = zz
            
            self.lective_days = self.school_calendar_id.count_lective_days(dstart=dtstart_o, dend=dtend_o)
            
    school_calendar_id = fields.Many2one('itbampa.school.calendar', string="School Calendar", required=True, default=_get_default_school_calendar)
    month_id = fields.Many2one('itbampa.activity.report.wizard.month', required=True, ondelete="cascade", string="Mes")
    line_ids = fields.One2many('itbampa.activity.report.wizard.line', 'wizard_id', compute='_get_line_ids')
    lective_days = fields.Integer(string="Total Lective Days", compute='_get_line_ids')
    
    
    @api.multi
    def print_monthly_report(self):
        return {
            'context': self._context,
            'data': {},
            'type': 'ir.actions.report.xml',
            'report_name': 'itbampa.activity_monthly_report',
            'report_type': 'qweb-html',
            'report_file': 'itbampa.activity_monthly_report',
            }
            
class LunchReportWizardLines(models.TransientModel):
    _name = 'itbampa.activity.report.wizard.line'
    _order = 'partner, product'
    
    wizard_id = fields.Many2one('itbampa.activity.report.wizard', ondelete="cascade")
    partner = fields.Char(string="Member")
    product = fields.Char(string="Product")
    total = fields.Integer(string="Total")

class LunchReportWizardMonths(models.TransientModel):
    _name = 'itbampa.activity.report.wizard.month'
    _order = 'year, month'
    
    @api.one
    @api.depends('year', 'month')
    def _get_month_name(self):
        if self.year > 0 and self.month > 0:
            self.name = date(self.year, self.month, 1).strftime('%B %Y')
    
    name = fields.Char(string="Month", compute='_get_month_name', store=True)
    year = fields.Integer(string="Year")
    month = fields.Integer(string="Month")   
    
class LunchCustomReport(models.AbstractModel):
    _name = 'report.itbampa.activity_monthly_report'
    
    @api.multi
    def render_html(self, data=None):
        report_obj = self.env['report']
        report = report_obj._get_report_from_name('itbampa.activity_monthly_report')
        active_id = self._context.get('active_id')
        wizard_obj = self.env[report.model].browse(active_id)
        docargs = {
            'doc_ids': self._ids,
            'doc_model': report.model,
            'docs': wizard_obj,
        }
        return report_obj.render('itbampa.activity_monthly_report', docargs)
