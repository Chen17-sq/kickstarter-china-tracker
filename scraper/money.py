"""Project-currency conversion using Kickstarter's explicit USD exchange rate.

Contract: kickstarter/android-oss app/src/main/graphql/schema.graphqls,
Project.currency + usdExchangeRate; Money.amount + currency. Visitor fxRate
is deliberately excluded because its destination currency is user-dependent.
"""
from .observations import number


def to_usd(amount, currency, project_currency, usd_rate):
    amount = number(amount)
    if amount is None or not isinstance(currency, str):
        return None
    if currency == 'USD':
        rate = 1.0
    elif currency == project_currency:
        rate = number(usd_rate)
    else:
        return None
    if rate is None or rate <= 0:
        return None
    usd = number(amount * rate)
    if usd is None:
        return None
    return {'amount': usd, 'native_amount': amount, 'currency': currency,
            'rate': rate, 'source': 'ks_project_usd_exchange_rate',
            'basis': 'native_usd' if currency == 'USD' else f'ks_project_usd:{currency}'}


def observe_money(row, key, converted, *, at, source):
    from .observations import observe
    if converted is None:
        return False
    if not observe(row, key, converted['amount'], at=at, source=source, basis=converted['basis']):
        return False
    row['observations'][key]['conversion'] = {
        k: converted[k] for k in ('native_amount', 'currency', 'rate', 'source')}
    row['observations'][key]['conversion']['observed_at'] = at
    return True
