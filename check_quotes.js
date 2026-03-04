const fs = require('fs');
const html = fs.readFileSync('c:/Users/msi/Desktop/مجلد جديد (2)/accounting_system/templates/orders.html', 'utf8');

const lines = html.split('\n');
let insideScript = false;
let errLines = [];

for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.includes('<script') && !line.includes('application/json')) {
        insideScript = true;
        continue;
    }
    if (line.includes('</script>')) {
        insideScript = false;
        continue;
    }

    if (insideScript) {
        // Check if there is an unterminated single quote or double quote without trailing slash
        // This is a naive check but can find unescaped newlines in string literals
        // Let's count quotes
        let s_quotes = 0;
        let d_quotes = 0;
        for (let j = 0; j < line.length; j++) {
            if (line[j] === "'" && (j === 0 || line[j - 1] !== '\\')) s_quotes++;
            if (line[j] === '"' && (j === 0 || line[j - 1] !== '\\')) d_quotes++;
        }

        // If quotes are odd, it might be an unclosed string if it's not a comment
        if (!line.trim().startsWith('//') && (s_quotes % 2 !== 0 || d_quotes % 2 !== 0)) {
            // Try to see if it is broken
            errLines.push((i + 1) + ': ' + line);
        }
    }
}

if (errLines.length) {
    console.log("Odd number of quotes found on lines:");
    errLines.forEach(l => console.log(l));
} else {
    console.log("No odd quotes found.");
}
