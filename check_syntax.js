const fs = require('fs');
const html = fs.readFileSync('c:/Users/msi/Desktop/مجلد جديد (2)/accounting_system/templates/orders.html', 'utf8');

// Replace jinja syntax with string 'dummy' so it doesn't break JS compilation
// Because Jinja tags like {{ something }} or {% if %} inside JS strings or outside will be syntax errors in raw JS
let cleanHtml = html.replace(/\{\{[\s\S]*?\}\}/g, '"dummy"');
cleanHtml = cleanHtml.replace(/\{%[\s\S]*?%\}/g, '');

const scripts = cleanHtml.match(/<script[\s\S]*?<\/script>/gi);
if (scripts) {
  scripts.forEach((script, i) => {
    if(!script.includes('type="application/json"')) {
      const jsCode = script.replace(/<script[^>]*>/i, '').replace(/<\/script>/i, '');
      try {
        new (require('vm').Script)(jsCode);
        console.log('Script ' + i + ' OK');
      } catch(e) {
        console.log('Script ' + i + ' ERROR:');
        console.log(e.toString());
        // Find line number
        if(e.stack) {
             const match = e.stack.match(/evalmachine\.<anonymous>:(\d+)/);
             if(match) {
                 const lineObj = match[1];
                 console.log("Error around line: " + lineObj);
                 const lines = jsCode.split('\n');
                 const lineStart = Math.max(0, lineObj - 3);
                 const lineEnd = Math.min(lines.length, parseInt(lineObj) + 2);
                 for(let j = lineStart; j < lineEnd; j++) {
                     console.log((j+1) + ': ' + lines[j]);
                 }
             }
        }
      }
    }
  });
}
