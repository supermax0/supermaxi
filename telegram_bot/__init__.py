# telegram_bot — تكامل بوت تيليجرام مع الذكاء الاصطناعي
# يستقبل الرسائل عبر webhook، يولد الرد عبر OpenAI، ويرسل الرد إلى المستخدم.

from telegram_bot.webhook import telegram_bp

__all__ = ["telegram_bp"]
