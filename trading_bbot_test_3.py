'''
This is a stripped down bot for just monitoring trade status and reporting to slack
to run script, type trading_bbot_test.py <trading_currency: eg, 'ETHBTC'> <buy_unit: eg. 0.001>
'''

from binance.client import Client
import pandas as pd
import numpy as np
import time  # waits
from slackclient import SlackClient
import sys

script, bot_name, trading_currency, buy_unit, round_dec, margin = sys.argv


# Get tokens from a txt file named tokens.txt in the same dir
with open('tokens.txt') as tokenfile: #store tokens in as text file to read (public, private, slack)
	[token1,token2,slack_token] = [line.split('\r\n')[0] for line in tokenfile]
	

currencies = {'NANOBTC': ['NANO', 'BTC'],
              'NANOETH': ['NANO', 'ETH'],
              'LTCBTC': ['LTC', 'BTC'],
              'LUNETH': ['LUN', 'ETH'],
              'ETHBTC': ['ETH', 'BTC'],
              'VENETH': ['VEN', 'ETH']}

num_bad_trades = 0

class trade_tracking_bot(object):
    def __init__(self, currency=trading_currency):
        self.curr_act = 'bought'
        self.trade_complete = False
        self.trading_currency = currency
        self.rounding = int(round_dec)  # 7 decimal places for BTC, 6 for ETH
        self.margin = np.float64(margin)  # expected profit /2
        self.buy_unit = np.float64(buy_unit)
        self.sell_unit = 'all'
        self.tries = 3  # try to sign in 3 times
        self.client = Client(token1, token2)
        self.hold_count = 0
        self.stay_signed = True
        self.monitor_trade = True
        self.trading_now = False  # monitor first
        self.orderId = 0
        self.orderID = 1
        self.mycurrtrade = self.check_trade()
        self.last_sold_price = 0
        self.last_bought_price = 0
        self.timeout = time.time() + (15 * 60)
        self.timout_counter = 0

        self.staying_signed(self.trading())

# posts to slack
    def slack_message(self, message):
        token = slack_token
        sc = SlackClient(token)

        sc.api_call('chat.postMessage', channel='trading_notifications',
                    text=message, username=bot_name, icon_emoji=':robot_face:')

# pings server, reporst server status if not
    def staying_signed(self, func):
        while self.stay_signed == True:
            if self.client.ping == {}:  # ping server ever 5 seconds
                return func
            else:
                server_status = self.client.get_system_status().get('msg')
                if server_status == 'normal':
                    # sign in again if ping fails
                    self.client = Client(token1, token2)
                else:
                    self.tries -= 1
                    time.sleep(3)  # sleep for 3 seconds
                    if self.tries == 0:
                        self.slack_message(
                            'Binance server down:' + server_status)
                        self.stay_signed = False

    def get_depth(self):  # one call to API to get price depth - can be interfaced with something like ta-lib for more indicators
        depthdf = pd.DataFrame(self.client.get_order_book(
            symbol=self.trading_currency))
        asks = pd.DataFrame(depthdf['asks'].values.tolist(), columns=[
                            'Price', 'Volume', 'other']).iloc[:, :2].apply(np.float64)
        bids = pd.DataFrame(depthdf['bids'].values.tolist(), columns=[
                            'Price', 'Volume', 'other']).iloc[:, :2].apply(np.float64)

        # get current market price
        allbids = bids.groupby(['Price']).aggregate(
            sum).sort_index(ascending=False).cumsum()
        allasks = asks.groupby(['Price']).aggregate(sum).cumsum()
        curr_market_price = (
            allbids.index.values[0] + allasks.index.values[0]) / 2
        area_bids = np.trapz(y=allbids['Volume'], dx=1)
        area_asks = np.trapz(y=allasks['Volume'], dx=1)
        ratio = area_bids / area_asks
        return (curr_market_price, ratio)

# interprets market depth information to decide whether to buy or sell
    def interpret_depth(self):
        curr_market_price, ratio = self.get_depth()
        price = 0  # price to act on
        if self.curr_act == 'sold':  # need to buy or hold
            if ratio > 1.2:
                act = 'buy_market'
                price = curr_market_price
            elif ratio < 0.3:
                act = 'hold'
                price = np.float64(
                    np.round((1 - self.margin) * curr_market_price, self.rounding))
            else:
                act = 'buy'  # buy at 1% below market
                # round to 7 decimal places for BTC
                price = np.float64(
                    np.round((1 - self.margin) * curr_market_price, self.rounding))
        elif self.curr_act == 'bought':
            if ratio < 0.3:
                act = 'sell_market'
                price = curr_market_price
            elif ratio > 1.2:
                act = 'hold'
                price = np.float64(
                    np.round((1 + self.margin) * curr_market_price, self.rounding))
            else:
                act = 'sell'  # seel at 1% above market
                # round to 7 decimal places for BTC
                price = np.float64(
                    np.round((1 + self.margin) * curr_market_price, self.rounding))
        return act, price

    def check_balances(self):
        return [np.float64(self.client.get_asset_balance(currency).get('free')) for currency in currencies.get(self.trading_currency)]

    def check_trade(self):
        mycurrtrade = self.client.get_all_orders(
            symbol=self.trading_currency)[-1]
        return(mycurrtrade)

# decides the trade details (buy, hold, sell) according to market_depth analysis
# Also makes sure that trade is in line with at available resources: BNB balance (fees), buying currency, selling currency, threshold for loss
    def trade_decision(self):
        # get balances
        BNB_bal = np.float64(self.client.get_asset_balance('BNB').get('free'))
        [bal1, bal2] = self.check_balances()
        # what the market depth suggests

        depth_act, depth_price = self.interpret_depth()
        action, price = depth_act, depth_price
        # hold count
        if BNB_bal < 0.1:
            self.trading_now = False
            self.slack_message(
                'BNB balance running low, plese top-up, trade suspended')

        if self.hold_count < 51:
            if depth_act == 'hold':
                action = 'hold'
                price = 999
                self.hold_count += 1
                print('Decided to hold', self.hold_count)
                time.sleep(3)
                self.trade_decision()

            if self.curr_act == 'sold':  # sold ALTcoin now need to buy BTC
                if bal2 < (self.buy_unit * depth_price):
                    self.buy_unit = bal2 / depth_price
                    self.slack_message('{} balance running low, plese top-up, trading less for now'.format(
                        currencies.get(self.trading_currency)[1]))

                if depth_act == 'buy_market':
                    if depth_price < (1 + self.margin) * self.last_sold_price:
                        self.hold_count = 0
                        action = 'buy_market'
                        price = depth_price

                    else:
                        self.hold_count += 1
                        action = 'hold'
                        print('Market price overe threshold, holding',
                              self.hold_count)
                        price = 999
                        time.sleep(3)
                        self.trade_decision()

                if depth_act == 'buy':
                    if depth_price < ((1 + self.margin) * self.last_sold_price):
                        hold_count = 0
                        action = 'buy'
                        price = depth_price

                    elif depth_price > ((1 + self.margin) * self.last_sold_price) and self.hold_count < 50:
                        self.hold_count += 1
                        action = 'hold'
                        price = 999
                        print('Buy price over threshold, holding', self.hold_count)
                        time.sleep(3)
                        self.trade_decision()

            if self.curr_act == 'bought':  # bought ALTcoin now need to sell ALTcoin
                if bal1 < self.buy_unit:
                    self.buy_unit -= 0.1
                    self.slack_message('{} balance running low, something is wrong here'.format(
                        currencies.get(self.trading_currency)[0]))

                if depth_act == 'sell_market':
                    if depth_price > self.last_bought_price:
                        self.hold_count = 0
                        action = 'sell_market'
                        price = depth_price

                    else:
                        self.hold_count += 1
                        action = 'hold'
                        price = 999
                        print(
                            'Market price under last bought price, holding', self.hold_count)
                        time.sleep(3)
                        self.trade_decision()

                if depth_act == 'sell':
                    if depth_price > self.last_bought_price:
                        self.hold_count = 0
                        action = 'sell'
                        price = depth_price

                    elif depth_price < self.last_bought_price:
                        self.hold_count += 1
                        action = 'hold'
                        print(
                            'Sell price under last bought price, holding', self.hold_count)
                        price = 999
                        time.sleep(3)
                        self.trade_decision()

        else:
            if depth_act != 'hold':
                action = depth_act
                price = depth_price
                self.hold_count = 0
            else:
                time.sleep(60)
                self.trade_decision()  # try in a minute

        print(action, price)
        return action, price


# Initiates trade according to trade decision
    def perform_trading(self, act, myprice):
        self.orderID += 1

        print('performing trade')
        if act == 'buy_market':
            order = self.client.create_order(
                symbol=trading_currency,
                side=Client.SIDE_BUY,
                type=Client.ORDER_TYPE_MARKET,
                quantity=buy_unit
            )
            self.trade_complete = False
            self.slack_message('Trade initiated: *buying* {} at {}, ID: {}'.format(
                self.trading_currency, self.buy_unit * myprice, self.orderID))
        elif act == 'sell_market':
            order = self.client.create_order(
                symbol=trading_currency,
                side=Client.SIDE_SELL,
                type=Client.ORDER_TYPE_MARKET,
                quantity=buy_unit
            )
            self.trade_complete = False
            self.slack_message('Trade initiated: *selling* {} at {}, ID: {}'.format(
                self.trading_currency, self.buy_unit * myprice, self.orderID))
        elif act == 'buy':
            order = self.client.create_order(
                symbol=trading_currency,
                side=Client.SIDE_BUY,
                type=Client.ORDER_TYPE_LIMIT,
                icebergQty=0,
                timeInForce='GTC',
                price=myprice,
                quantity=buy_unit
            )
            self.trade_complete = False
            self.slack_message('Trade initiated: *buying* {} at {}, ID: {}'.format(
                self.trading_currency, self.buy_unit * myprice, self.orderID))
        elif act == 'sell':
            order = self.client.create_order(
                symbol=trading_currency,
                side=Client.SIDE_SELL,
                type=Client.ORDER_TYPE_LIMIT,
                icebergQty=0,
                timeInForce='GTC',
                price=myprice,
                quantity=buy_unit
            )
            self.trade_complete = False
            self.slack_message('Trade initiated: *selling* {} at {}, ID: {}'.format(
                self.trading_currency, self.buy_unit * myprice, self.orderID))
        elif act == 'hold':
           self.trade_complete = True

        else:  # interrupt
            self.slack_message('ERROR: CLOSING OPERATIONS')
            sys.exit()
        return act, myprice
# monitor trade: Monitors trade status and decides trading now and trade complete variables to allow further trades
# Posts completed trade details to slack with profits/losses included
# Also counts badtrades for reporting

    def trading_monitor(self):
        global num_bad_trades
        bad_trades = 0
        print('monitoring trade')

        my_last_trades = pd.DataFrame(
            self.client.get_my_trades(symbol=self.trading_currency))

        self.last_bought_price = self.buy_unit* np.float64(
            my_last_trades[my_last_trades['isBuyer'] == True].iloc[-1, :]['price'])
        self.last_sold_price = self.buy_unit*np.float64(
            my_last_trades[my_last_trades['isBuyer'] == False].iloc[-1, :]['price'])

        self.mycurrtrade = self.check_trade()

        while self.mycurrtrade.get('status') == 'NEW':  # continue
            self.trading_now = False  # stop trading
            self.trade_complete = False
            time.sleep(1)
            self.mycurrtrade = self.check_trade()

        if (self.mycurrtrade.get('status') == 'FILLED') and self.orderId != self.mycurrtrade.get('orderId'):
            self.trade_complete = True
            self.timeout = time.time() + (60 * 15)  # reset timer
            self.timeout_counter = 0

            print('starting trade')
            self.orderId = self.mycurrtrade.get('orderId')
            trade_total = np.float64(self.mycurrtrade.get(
                'executedQty')) * np.float64(self.mycurrtrade.get('price'))

            if self.mycurrtrade.get('side') == 'SELL':
                trade_diff = trade_total - self.last_bought_price
                self.curr_act = 'sold'
                self.trading_now = True
                self.slack_message('Sold: {} {} for {}, difference = *{}*'.format(self.mycurrtrade.get('executedQty'),
                                                                                  self.trading_currency,
                                                                                  trade_total,
                                                                                  trade_diff))
                if trade_diff < 0 and bad_trades < 3:
                    bad_trades += 1
                elif trade_diff < 0 and bad_trades == 3:
                    bad_trades += 1
                    self.slack_message(
                        'More than 3 bad trades made, in a row!')
                elif trade_diff >= 0:
                    num_bad_trades += bad_trades
                    bad_trades = 0

            elif self.mycurrtrade.get('side') == 'BUY':  # bought something
                trade_diff = trade_total - self.last_sold_price
                self.curr_act = 'bought'
                self.trading_now = True
                self.slack_message('Bought: {} {} for {}, difference = *{}*'.format(self.mycurrtrade.get('executedQty'),
                                                                                    self.trading_currency,
                                                                                    trade_total,
                                                                                    trade_diff))
                if trade_diff > 0 and bad_trades < 3:
                    bad_trades += 1
                elif trade_diff > 0 and bad_trades == 3:
                    bad_trades += 1
                    self.slack_message('More than 3 bad trades made!')

                elif trade_diff <= 0:
                    num_bad_trades += bad_trades
                    bad_trades = 0
            return('trade done')
        if (self.mycurrtrade.get('status') == 'FILLED') and self.orderId == self.mycurrtrade.get('orderId'):
            pass

        time.sleep(1)  # check every second

# Trading wrapper, only allows trading if both trading_now and trade_complete are true
    def trading(self):

        while self.trading_now == False or self.trade_complete == False:
            self.trading_monitor()  # just monitor trades

        else:
            while time.time() < self.timeout:
                print('bot has decided to trade')
                # perform trade

                newact, newprice = self.trade_decision()  # decides prices and actions
                print('Now trading ', newact, newprice)
                self.perform_trading(newact, newprice)
                self.trading_now = False
                self.trading_monitor()
                time.sleep(1)

            else:
                self.timout_counter += 1
                if self.timeout_counter < 3:
                    self.timeout = time.time() + (15 * 60)  # reset time limit
                    newact, newprice = self.trade_decision()  # decides prices and actions
                    self.perform_trading(newact, newprice)
                    self.trading_now = False
                    self.trading_monitor()
                else:
                    self.trading_now = False
                    self.slack_message(
                        'No trade has been made for 45 min consequtively. QUITTING')
                    self.timeout_counter = 0


trade_tracking_bot()
