'''
This is a stripped down bot for just monitoring trade status and reporting to slack
'''

from binance.client import Client
import pandas as pd
import numpy as np
import time #waits 
from slackclient import SlackClient
import sys

script, bot_name, trading_currency = sys.argv


# sign in: store binance and slack tokens in a txt file named token.txt
with open('tokens.txt') as tokenfile: #store tokens in as text file to read (public, private, slack)
	[token1,token2,slack_token] = [line.split('\n')[0] for line in tokenfile]
	
stay_signed = True
num_bad_trades = 0



class trade_tracking_bot(object):
	def __init__(self):
		self.curr_act= 'bought'
		self.trading_now = True
		self.trading_currency = trading_currency
		self.rounding = 7 # 7 decimal places for BTC
		self.buy_unit = 1.5 # how much NANO to buy each time 
		self.sell_unit = 'all'
		self.tries = 3 # try to sign in 3 times
		self.client = Client(token1, token2)
		self.stay_signed = stay_signed
		self.orderId = 0
		self.staying_signed(self.trading_monitor())
		
	
	def slack_message(self, message):
	    token = slack_token
	    sc = SlackClient(token)
	    
	    sc.api_call('chat.postMessage', channel = 'trading_notifications',
	               text = message, username = bot_name, icon_emoji= ':robot_face:')



	def staying_signed(self, func):
		while self.stay_signed == True:
			if self.client.ping == {}: # ping server ever 5 seconds
				return func
			else:
				server_status = self.client.get_system_status().get('msg')
				if server_status == 'normal':
					self.client = Client(token1, token2) # sign in again if ping fails
				else:
					self.tries -= 1
					time.sleep(3) #sleep for 3 seconds
					if self.tries == 0:
						self.slack_message('Binance server down:'+server_status)
						self.stay_signed = False

	
	def check_trade(self):
		mycurrtrade = self.client.get_all_orders(symbol = self.trading_currency)[-1]
		return(mycurrtrade)

	def trading_monitor(self):
		
		global num_bad_trades
		
		bad_trades= 0
		mycurrtrade = self.check_trade()
		my_last_trades = pd.DataFrame(self.client.get_my_trades(symbol = self.trading_currency ))
		
		last_bought_price = np.float64(my_last_trades[my_last_trades['isBuyer']==True].iloc[-1,:]['price'])
		last_sold_price = np.float64(my_last_trades[my_last_trades['isBuyer']==False].iloc[-1,:]['price'])
		
		if mycurrtrade.get('status') == 'NEW': # continue 
			pass
		elif mycurrtrade.get('status') == 'FILLED' and self.orderId != mycurrtrade.get('orderId'): # reset when filled
			self.orderId = mycurrtrade.get('orderId')
			trade_total = np.float64(mycurrtrade.get('executedQty'))*np.float64(mycurrtrade.get('price'))
	            
			if mycurrtrade.get('side')== 'SELL':
				trade_diff = trade_total - last_bought_price
				self.curr_act = 'sold'
				self.slack_message('Sold: {} {} for {}, difference = *{}*'.format(mycurrtrade.get('executedQty'), 
		                                                          self.trading_currency, 
		                                                          trade_total,
		                                                          trade_diff))                
				if trade_diff < 0 and bad_trades < 3:
					bad_trades +=1
				elif trade_diff<0 and bad_trades ==3:
					bad_trades += 1
					self.slack_message('More than 3 bad trades made, in a row!')
				elif trade_diff>=0:
					num_bad_trades += bad_trades
					bad_trades = 0
			else: #bought something
				trade_diff = trade_total - last_sold_price
				self.curr_act = 'bought'
				self.slack_message('Bought: {} {} for {}, difference = *{}*'.format(mycurrtrade.get('executedQty'), 
	                                          self.trading_currency, 
	                                          trade_total,
	                                          trade_diff))
				if trade_diff > 0 and bad_trades < 3:
					bad_trades +=1
				elif trade_diff > 0 and bad_trades ==3:
					bad_trades += 1
					self.slack_message('More than 3 bad trades made!')

				elif trade_diff<=0:
					num_bad_trades += bad_trades
					bad_trades = 0

		time.sleep(1)# check every second
		self.trading_monitor()



trade_tracking_bot()
