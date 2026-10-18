"""Public forms render without business databases or external payments."""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from flask import Flask, flash, render_template

ROOT = Path(__file__).resolve().parents[1]
PAGES = ['login', 'signup', 'pricing', 'signup_whatsapp_pending', 'payment',
         'zaincash_checkout', 'payment_success', 'payment_failed',
         'change_password', 'upgrade_required', 'terms', 'privacy']


def make_app():
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.config.update(SECRET_KEY='isolated-template-tests', TESTING=True, TEMPLATES_AUTO_RELOAD=True)
    for endpoint, path in [('index.login_tenant', '/login/<tenant_slug>'),
                           ('index.change_password', '/account/change-password'),
                           ('index.logout', '/logout'),
                           ('index.signup_whatsapp_pending', '/signup/whatsapp-pending'),
                           ('payments.checkout', '/payments/checkout')]:
        app.add_url_rule(path, endpoint, lambda **kwargs: '', methods=['GET'])
    return app


def context():
    plans = {
        'free': dict(key='free', name='المجانية', price_monthly=0, price_yearly=0, max_users=3, max_orders_monthly=500),
        'basic': dict(key='basic', name='الأساسية', price_monthly=25000, price_yearly=250000, max_users=5, max_orders_monthly=1000),
        'pro': dict(key='pro', name='المتقدمة', price_monthly=45000, price_yearly=450000, max_users=15, max_orders_monthly=10000),
        'enterprise': dict(key='enterprise', name='الشركات', price_monthly=90000, price_yearly=900000),
    }
    return dict(plans_dict=plans, selected_plan=plans['basic'], billing='monthly', free_trial_days=14,
                welcome_offer_available=False, offer_key='', form={}, plan_key='basic',
                plans=[dict(key=p['key'], name=p['name'], description='مساحة عمل لإدارة نشاطك',
                            price=p['price_monthly'], original_price=None,
                            features=['إدارة المبيعات والمخزون', 'الحسابات والتقارير', 'العمل من المتصفح وسطح المكتب'])
                       for p in plans.values()],
                plan=dict(key='basic', name='الأساسية', price=25000),
                amount=25000, checkout_prefill={}, tenant=dict(name='متجر النور', slug='alnoor'),
                registration=dict(company_name='متجر النور', contact_name='حساب تجريبي', phone='07700000000', activation_code='DEMO-123'),
                whatsapp_url='https://wa.me/9647700000000?text=preview', is_activated=False,
                platform_app_name='FINORA', multi_tenant_tip=True, is_clinics_business=True)


def render(page, overrides=None, **request_kwargs):
    app = make_app()
    data = context()
    data.update(overrides or {})
    with app.test_request_context('/', **request_kwargs):
        flash('رسالة اختبار <script>unsafe</script>', 'error')
        return render_template(page + '.html', **data)


@pytest.mark.parametrize('page', PAGES)
def test_public_page_renders_and_preserves_escaped_feedback(page):
    html = render(page)
    soup = BeautifulSoup(html, 'html.parser')
    assert len(soup.select('main')) == 1
    assert soup.select_one('h1')
    assert soup.html['dir'] == 'rtl'
    assert 'css/public-flow.css' in html
    assert '&lt;script&gt;unsafe&lt;/script&gt;' in html


def test_login_preserves_switch_and_fixed_tenant_contract_without_echoing_password():
    html = render('login', dict(fixed_tenant_slug='fixed', switch_warning=True,
                              active_tenant_slug='old', pending_tenant_slug='fixed'),
                  method='POST', data={'username': '<unsafe>', 'password': 'do-not-render-this'})
    soup = BeautifulSoup(html, 'html.parser')
    assert soup.select_one('#loginForm')['action'] == '/login/fixed'
    assert soup.select_one('#tenant_slug')['value'] == 'fixed'
    assert soup.select_one('[name=confirm_switch]')['value'] == '1'
    assert soup.select_one('#username')['value'] == '<unsafe>'
    assert 'do-not-render-this' not in html


def test_signup_uses_only_available_plans_and_keeps_submission_contract():
    plans = {'custom': dict(key='custom', name='خطة خاصة', price_monthly=123, price_yearly=456)}
    soup = BeautifulSoup(render('signup', dict(plans_dict=plans, selected_plan=plans['custom'],
                                              billing='yearly', form={'password': 'never-echo'})), 'html.parser')
    assert [el['data-plan'] for el in soup.select('[data-plan]')] == ['custom']
    assert soup.select_one('#plan_key_input')['value'] == 'custom'
    assert soup.select_one('#billing_input')['value'] == 'yearly'
    assert soup.select_one('form')['action'] == '/signup'
    assert soup.select_one('#whatsapp_confirmed').has_attr('required')
    assert not soup.select_one('#password').has_attr('value')
    assert not soup.select_one('[name=marketing_opt_in]').has_attr('checked')


def test_checkout_preserves_amount_hidden_fields_and_upload():
    soup = BeautifulSoup(render('zaincash_checkout', dict(amount=450000, plan_key='pro', billing='yearly',
                        checkout_prefill={'tenant_name': 'alnoor'})), 'html.parser')
    form = soup.select_one('form')
    assert form['action'] == '/payments/zaincash-submit'
    assert form['enctype'] == 'multipart/form-data'
    assert form.select_one('[name=plan_key]')['value'] == 'pro'
    assert form.select_one('[name=billing]')['value'] == 'yearly'
    assert form.select_one('#tenant_name').has_attr('readonly')
    assert form.select_one('#receipt_image')['accept'] == 'image/png,image/jpeg,application/pdf'
    assert '450,000' in soup.get_text()


def test_activation_states_do_not_offer_login_until_activated():
    pending = BeautifulSoup(render('signup_whatsapp_pending'), 'html.parser')
    active = BeautifulSoup(render('signup_whatsapp_pending', {'is_activated': True}), 'html.parser')
    assert pending.select_one('a[href^="https://wa.me/"]')
    assert not pending.select_one('a[href="/login/alnoor"]')
    assert active.select_one('a[href="/login/alnoor"]')
    assert not active.select_one('a[href^="https://wa.me/"]')


def test_password_change_retains_server_constraints():
    soup = BeautifulSoup(render('change_password', {'forced': True}), 'html.parser')
    assert soup.select_one('form')['action'] == '/account/change-password'
    for field in ['new_password', 'confirm_password']:
        assert soup.select_one('#' + field)['minlength'] == '10'
        assert soup.select_one('#' + field).has_attr('required')
