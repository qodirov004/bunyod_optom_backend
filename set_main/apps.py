from django.apps import AppConfig


class SetMainConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'set_main'

    def ready(self):
        # Импортируем signals, чтобы они были зарегистрированы
        import set_main.signals
