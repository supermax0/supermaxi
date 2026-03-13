from app import app
from routes.autoposter import run_scheduled_posts_for_all_tenants


def main() -> None:
    with app.app_context():
        run_scheduled_posts_for_all_tenants(app)


if __name__ == "__main__":
    main()

