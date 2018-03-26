# crypto_bot

## Crypto bot: monitoring_bbot.py

Monitors binance trades of one currency pair per instance through the python-binance API (https://github.com/sammchardy/python-binance). Any trading activity is then reported to a slack channel (I've named mine #trading-notifications, but that can change).

Trading activities include placing an order, or successful fulfillment of a trade. 

Usage (command line):

$cd \<directory\>

$python monitoring_bbot.py, \<'my bot name'\>, \<'trading currency pair'\>

for list of trading pairs: https://github.com/binance-exchange/binance-official-api-docs/blob/master/rest-api.md
