import re

with open('e:/Mr_Delivery/shop/consumers.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. ChatConsumer.chat_message
chat_target = '''    async def chat_message(self, event):
        """إرسال رسالة الشات"""
        await self.send(text_data=_json_dumps({
            'type': 'chat_message',
            'data': event['message']
        }))'''

chat_replace = '''    async def chat_message(self, event):
        """إرسال رسالة الشات"""
        from user.utils import localize_message
        msg_data = dict(event['message'])
        msg_data['content'] = localize_message(None, msg_data.get('content'), lang=getattr(self, 'lang', 'ar'))
        await self.send(text_data=_json_dumps({
            'type': 'chat_message',
            'data': msg_data
        }))'''

text = text.replace(chat_target, chat_replace)

# 2. All new_message handlers
new_msg_pattern = r'''    async def new_message\(self, event\):
        \"\"\"[^\"]+?\"\"\"
        await self\.send\(text_data=_json_dumps\(\{
            'type': 'new_message',
            'data': event\['data'\]
        \}\)\)'''

new_msg_replace = '''    async def new_message(self, event):
        """إشعار برسالة جديدة"""
        from user.utils import localize_message
        notif_data = dict(event['data'])
        if 'message' in notif_data and isinstance(notif_data['message'], dict):
            notif_data['message'] = dict(notif_data['message'])
            notif_data['message']['content'] = localize_message(
                None, notif_data['message'].get('content'), lang=getattr(self, 'lang', 'ar')
            )
        await self.send(text_data=_json_dumps({
            'type': 'new_message',
            'data': notif_data
        }))'''

text = re.sub(new_msg_pattern, new_msg_replace, text)

# 3. Add lang extraction to connect methods of OrderConsumer and CustomerOrderConsumer
order_customer_connect_pattern = r'''        self.room_group_name = f'(?:customer_orders_|shop_orders_)\{self\.(?:customer_id|shop_owner_id)\}'
        
        user = self\.scope\.get\('user'\)'''

def add_lang(match):
    prefix = match.group(0).split('user = ')[0]
    return prefix + '''query_string = self.scope.get('query_string', b'').decode('utf-8')
        self.lang = 'ar'
        if 'lang=' in query_string:
            self.lang = query_string.split('lang=')[-1].split('&')[0]
        
        user = self.scope.get('user')'''

text = re.sub(order_customer_connect_pattern, add_lang, text)

with open('e:/Mr_Delivery/shop/consumers.py', 'w', encoding='utf-8') as f:
    f.write(text)
