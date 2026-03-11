Build a Windows desktop application called **Finora Deploy Studio** that allows me to deploy my project to GitHub and then automatically update my Linux server.

Requirements:

Create a GUI application using **Python + Tkinter (or PySide6 if preferred)**.

The interface must contain:

1. A button **Push to GitHub**
2. A button **Deploy to Server**
3. A large **terminal/log output window**
4. A field to configure:

   * Local project path
   * Server SSH address
   * Server project path
5. A progress indicator.

Behavior:

When clicking **Push to GitHub**, the program should execute these commands inside the local project folder:

git add .
git commit -m "update"
git push

When clicking **Deploy to Server**, the program should connect via SSH and execute:

cd /var/www/finora/supermaxi
git pull
pkill -f gunicorn
source venv/bin/activate
gunicorn app:app -b 127.0.0.1:8000 -w 3 --daemon
systemctl restart nginx

All terminal output should appear in the UI terminal window.

Technical requirements:

• Use Python subprocess to run commands
• Use threading so the UI does not freeze
• Show live logs in the terminal window
• Allow editing server configuration in the UI
• Save configuration in a JSON file
• Provide error handling and clear log messages.

Bonus features:

• Button: Restart Server
• Button: View Server Logs
• Button: Build Frontend (run npm install + npm run build)
• Show Git status before push
• Dark theme UI.

The application should be clean, modern, and easy to use for developers.

Return the **complete Python code** for the application.
