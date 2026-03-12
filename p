Develop a built-in "Self Healing Server Monitor" inside Finora Deploy Studio.

The goal:
Add a live terminal panel that continuously monitors the production server and automatically repairs common failures.

The monitor must run 24/7 in a background thread.

Main features:

1) Live Terminal Panel
Create a terminal UI next to the existing log console.
It must stream real-time monitoring logs.

Display messages like:

[MONITOR] Checking nginx...
[MONITOR] Checking gunicorn...
[MONITOR] Checking disk usage...
[MONITOR] Checking SSL...
[MONITOR] Checking HTTP response...

If an error is detected show:

[ERROR DETECTED] nginx is down
[AUTO FIX] restarting nginx...

2) Continuous Health Check Loop

Run every 10 seconds.

Checks:

• nginx service
• gunicorn service
• flask response
• HTTPS status
• port 8000 listening
• disk usage
• RAM usage
• SSL certificate validity
• server load
• DNS resolution
• firewall status

3) Auto Repair Actions

If nginx is stopped:

systemctl restart nginx

If gunicorn is stopped:

systemctl restart gunicorn

If port 8000 closed:

restart gunicorn

If SSL expired:

certbot renew --nginx

If disk > 90%

clean logs:

journalctl --vacuum-time=3d

If nginx config broken:

nginx -t
then auto fix config

4) HTTP Health Check

Request:

https://domain

If response != 200

restart nginx and gunicorn.

5) Remote Execution

All checks run via SSH from the deploy tool.

Example command execution:

ssh root@server "systemctl status nginx"

6) Monitoring Dashboard

Add small status indicators:

NGINX: 🟢 / 🔴  
GUNICORN: 🟢 / 🔴  
HTTPS: 🟢 / 🔴  
CPU: %  
RAM: %  
DISK: %

7) Terminal Output Example

[17:21:04] Checking nginx...
[17:21:04] nginx running ✔

[17:21:05] Checking gunicorn...
[17:21:05] gunicorn running ✔

[17:21:06] Checking HTTPS...
[17:21:06] HTTP 200 ✔

[17:21:07] Checking disk usage...
[17:21:07] Disk 63% ✔

If problem:

[17:24:11] ERROR nginx stopped
[17:24:11] Restarting nginx...
[17:24:12] nginx restarted ✔

8) Background Thread

Implement as a Python thread:

ServerMonitorThread()

running infinite loop with sleep(10)

9) Safety

Avoid restart loops.
Limit auto fix attempts.

10) Button in UI

Add button:

"Start Monitor"

Once started it runs forever.

11) Logging

Store monitor logs in:

/var/log/finora_monitor.log

12) Implementation language

Python

Use:

paramiko for SSH
threading
queue for UI logs