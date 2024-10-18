import httpx
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

TOKEN = ""

class TradingBot:
    def __init__(self, initial_balance=100.0, grid_levels=10, percentage_change=1.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.grid_levels = grid_levels
        self.percentage_change = percentage_change / 100
        self.positions = []
        self.active_trades = []
        self.symbol = None
        self.auto_trade_active = False

    async def get_asset_list(self):
        url = 'https://api.binance.com/api/v3/ticker/price'
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
        data = response.json()
        assets = [item['symbol'] for item in data if item['symbol'].endswith('USDT')]
        return assets[:10]

    async def get_current_price(self, symbol):
        if symbol is None:
            raise ValueError("Символ не установлен.")
        
        url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}'
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
        data = response.json()
        return float(data['price'])

    async def select_asset(self, symbol):
        self.symbol = symbol

    async def initialize_grid(self):
        self.positions = []
        current_price = await self.get_current_price(self.symbol)
        for i in range(self.grid_levels):
            buy_price = current_price * (1 - self.percentage_change * (i + 1))
            self.positions.append({
                'buy_price': buy_price,
                'amount': self.initial_balance / self.grid_levels,
                'sold': False
            })

    async def simulate_price_change(self, current_price):
        change_percentage = random.uniform(-0.05, 0.05)
        return current_price * (1 + change_percentage)

    async def execute_trade(self):
        current_price = await self.get_current_price(self.symbol)
        current_price = await self.simulate_price_change(current_price)
        result = f"\nТекущая цена {self.symbol}: {current_price:.2f}\n"

        for position in self.positions:
            if not position['sold'] and current_price <= position['buy_price'] * (1 - self.percentage_change):
                result += f"Покупка на уровне {position['buy_price']:.2f}, сумма: {position['amount']:.2f}\n"
                self.active_trades.append({
                    'buy_price': position['buy_price'],
                    'amount': position['amount']
                })
                self.balance -= position['amount']
                position['sold'] = True

        for trade in self.active_trades[:]:
            sell_price = trade['buy_price'] * (1 + self.percentage_change)
            if current_price >= sell_price:
                result += f"Продажа на уровне {sell_price:.2f}, сумма: {trade['amount']:.2f}\n"
                self.balance += trade['amount'] * (1 + self.percentage_change)
                self.active_trades.remove(trade)

        result += f"Текущий баланс: {self.balance:.2f} USD\n"
        return result

    async def auto_trade(self, update: Update):
        while self.auto_trade_active:
            if self.symbol is None:
                await update.callback_query.answer("Пожалуйста, выберите актив для торговли.")
                self.auto_trade_active = False
                return

            result = await self.execute_trade()
            await update.callback_query.message.reply_text(result)
            await asyncio.sleep(5)

    async def buy_asset(self, amount):
        current_price = await self.get_current_price(self.symbol)
        total_cost = amount * current_price

        if total_cost > self.balance:
            return "Недостаточно средств для покупки."

        self.balance -= total_cost
        self.active_trades.append({
            'buy_price': current_price,
            'amount': amount
        })
        return f"Куплено {amount} {self.symbol} по цене {current_price:.2f} USD."

    async def sell_asset(self, amount):
        total_cost = 0
        for trade in self.active_trades:
            if trade['amount'] >= amount:
                current_price = await self.get_current_price(self.symbol)
                profit = (current_price - trade['buy_price']) * amount

                total_cost += profit
                self.balance += total_cost
                trade['amount'] -= amount
                if trade['amount'] == 0:
                    self.active_trades.remove(trade)

                return f"Продано {amount} {self.symbol} по цене {current_price:.2f} USD, прибыль: {profit:.2f} USD."

        return "Недостаточно активов для продажи."

bot = TradingBot()

def main_menu():
    keyboard = [
        [InlineKeyboardButton("Выбрать актив", callback_data='select')],
        [InlineKeyboardButton("Торговать", callback_data='trade')],
        [InlineKeyboardButton("Показать баланс", callback_data='balance')],
        [InlineKeyboardButton("Запустить авто-торговлю", callback_data='start_auto_trade')],
        [InlineKeyboardButton("Остановить авто-торговлю", callback_data='stop_auto_trade')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Привет! Я торговый бот. Выберите действие:", reply_markup=main_menu())

async def select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    assets = await bot.get_asset_list()
    keyboard = [
        [InlineKeyboardButton(f"{asset}", callback_data=f'asset_{asset}')] for asset in assets
    ]
    keyboard.append([InlineKeyboardButton("Назад в меню", callback_data='main_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выберите актив для торговли:", reply_markup=reply_markup)

async def set_asset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    asset_symbol = query.data.split('_')[1]
    await bot.select_asset(asset_symbol)
    await bot.initialize_grid()
    current_price = await bot.get_current_price(asset_symbol)
    await query.edit_message_text(
        f"Выбран актив: {asset_symbol}\nТекущая цена: {current_price:.2f} USD",
        reply_markup=main_menu()
    )

async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not bot.symbol:
        new_text = "Сначала выберите актив с помощью кнопки 'Выбрать актив'."
        if query.message.text != new_text:
            await query.edit_message_text(new_text, reply_markup=main_menu())
        return

    keyboard = [
        [InlineKeyboardButton("Купить", callback_data='buy')],
        [InlineKeyboardButton("Продать", callback_data='sell')],
        [InlineKeyboardButton("Назад в меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    new_text = "Выберите действие:"
    
    if query.message.text != new_text:
        await query.edit_message_text(new_text, reply_markup=reply_markup)

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    balance_info = f"Текущий баланс: {bot.balance:.2f} USD\n"

    await query.edit_message_text(balance_info, reply_markup=main_menu())

async def start_auto_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if bot.auto_trade_active:
        await query.edit_message_text("Авто-торговля уже активна.", reply_markup=main_menu())
        return

    bot.auto_trade_active = True
    await query.edit_message_text("Авто-торговля запущена. Бот будет автоматически проверять рынок.", reply_markup=main_menu())
    
    asyncio.create_task(bot.auto_trade(update))

async def stop_auto_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    current_text = query.message.text
    new_text = "Авто-торговля не активна."

    if current_text != new_text:
        await query.edit_message_text(new_text, reply_markup=main_menu())
    else:
        await query.answer("Сообщение уже обновлено.", show_alert=True)

    bot.auto_trade_active = False

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Выберите действие:", reply_markup=main_menu())

async def handle_trade_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    action = query.data
    await query.edit_message_text("Введите количество активов для торговли:")
    context.user_data['trade_action'] = action

async def handle_trade_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    amount_str = update.message.text
    try:
        amount = float(amount_str)
        action = context.user_data.get('trade_action')

        if action == 'buy':
            result = await bot.buy_asset(amount)
            await update.message.reply_text(result)
        elif action == 'sell':
            result = await bot.sell_asset(amount)
            await update.message.reply_text(result)
        
        await update.message.reply_text("Выберите следующее действие:", reply_markup=main_menu())
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число.")

def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(select, pattern='select'))
    application.add_handler(CallbackQueryHandler(set_asset, pattern='asset_'))
    application.add_handler(CallbackQueryHandler(trade, pattern='trade'))
    application.add_handler(CallbackQueryHandler(show_balance, pattern='balance'))
    application.add_handler(CallbackQueryHandler(start_auto_trade, pattern='start_auto_trade'))
    application.add_handler(CallbackQueryHandler(stop_auto_trade, pattern='stop_auto_trade'))
    application.add_handler(CallbackQueryHandler(main_menu_handler, pattern='main_menu'))
    application.add_handler(CallbackQueryHandler(handle_trade_action, pattern='buy|sell'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trade_amount))

    application.run_polling()

if __name__ == '__main__':
    main()