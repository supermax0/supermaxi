I want to add a "System Update" button in the top navigation bar of my Flask SaaS application (Finora).

Requirements:

1. Add a new admin-only API route:
POST /admin/system-update

2. The route must:
- Run git pull inside /var/www/finora/supermaxi
- Restart the finora service using systemctl restart finora
- Return JSON response {status: "success"} or {status: "error"}

3. The command execution should be done safely using subprocess.

Example Python logic:

import subprocess

subprocess.run(["git","pull"], cwd="/var/www/finora/supermaxi")
subprocess.run(["systemctl","restart","finora"])

4. Only allow admin users to trigger this endpoint.

5. In the base.html topbar add a button:

<button id="systemUpdateBtn">
Update System
</button>

6. Add JavaScript that calls the endpoint:

fetch('/admin/system-update',{
method:'POST'
})
.then(r=>r.json())
.then(data=>{
alert("System Updated Successfully")
})

7. Show loading spinner while updating.

8. The button should appear only for admin role.

9. Make sure the UI matches the existing Finora dashboard style.

10. Keep all code modular and place the route in routes/admin.py

Goal:
Allow the SaaS admin to update the entire system from the dashboard without SSH access.