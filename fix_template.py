import os

path = r'c:\Users\msi\Desktop\مجلد جديد (2)\accounting_system\templates\superadmin_base.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

bad_str = """            {
            % block extra_style %
        }

            {
            % endblock %
        }"""

bad_str2 = "            {\n            % block extra_style %\n        }\n\n            {\n            % endblock %\n        }"
bad_str3 = "            {\r\n            % block extra_style %\r\n        }\r\n\r\n            {\r\n            % endblock %\r\n        }"

if bad_str in content:
    content = content.replace(bad_str, "        {% block extra_style %}{% endblock %}")
elif bad_str2 in content:
    content = content.replace(bad_str2, "        {% block extra_style %}{% endblock %}")
elif bad_str3 in content:
    content = content.replace(bad_str3, "        {% block extra_style %}{% endblock %}")
else:
    # Just regex replace anything looking like it
    import re
    content = re.sub(r'\{[\s\r\n]+% block extra_style %[\s\r\n]+\}[\s\r\n]+{\s+% endblock %[\s\r\n]+\}', '{% block extra_style %}{% endblock %}', content)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Fix applied successfully!")
