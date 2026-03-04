const fs = require('fs');
const html = fs.readFileSync('c:/Users/msi/Desktop/مجلد جديد (2)/accounting_system/templates/orders.html', 'utf8');

// We don't want to replace with "dummy" because that breaks things if jinja is inside a string.
// Instead, let's replace {{ ... }} and {% ... %} with a safe placeholder that preserves JS syntax.
// If it's inside quotes: " {{ _('key') }} " -> we want it to remain valid. 
// Replacing {{ ... }} with `X` is usually safe.

let cleanHtml = html.replace(/\{\{.*?\}\}/g, 'X');
cleanHtml = cleanHtml.replace(/\{%.*?%\}/g, '');

const scripts = cleanHtml.match(/<script[\s\S]*?<\/script>/gi);
if (scripts) {
    scripts.forEach((script, i) => {
        if (!script.includes('type="application/json"')) {
            const jsCode = script.replace(/<script[^>]*>/i, '').replace(/<\/script>/i, '');
            try {
                new (require('vm').Script)(jsCode);
                console.log('Script ' + i + ' OK');
            } catch (e) {
                console.log('\n--- Script ' + i + ' ERROR ---');
                console.log(e.message);
                // Find line number
                if (e.stack) {
                    const match = e.stack.match(/evalmachine\.<anonymous>:(\d+)/);
                    if (match) {
                        const lineObj = match[1];
                        console.log("Error around line: " + lineObj);
                        const lines = jsCode.split('\n');
                        const lineStart = Math.max(0, lineObj - 5);
                        const lineEnd = Math.min(lines.length, parseInt(lineObj) + 5);
                        for (let j = lineStart; j < lineEnd; j++) {
                            console.log((j + 1) + ': ' + lines[j]);
                        }
                    }
                }
            }
        }
    });
}
