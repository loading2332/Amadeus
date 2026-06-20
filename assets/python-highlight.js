/* Lightweight, offline Python syntax highlighting for lesson code blocks. */
(() => {
  "use strict";

  const keywords = new Set([
    "and", "as", "assert", "async", "await", "break", "case", "class",
    "continue", "def", "del", "elif", "else", "except", "finally", "for",
    "from", "global", "if", "import", "in", "is", "lambda", "match",
    "nonlocal", "not", "or", "pass", "raise", "return", "try", "while",
    "with", "yield",
  ]);
  const literals = new Set(["False", "None", "True"]);
  const builtins = new Set([
    "bool", "dict", "enumerate", "float", "int", "len", "list", "object",
    "print", "range", "set", "str", "super", "tuple", "type", "zip",
  ]);

  const escapeHtml = (value) => value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");

  const token = (kind, value) =>
    `<span class="hljs-${kind}">${escapeHtml(value)}</span>`;

  function highlightPython(source) {
    let output = "";
    let index = 0;

    while (index < source.length) {
      const rest = source.slice(index);
      let match;

      if (source[index] === "#") {
        const end = source.indexOf("\n", index);
        const stop = end === -1 ? source.length : end;
        output += token("comment", source.slice(index, stop));
        index = stop;
        continue;
      }

      if (source[index] === "'" || source[index] === '"') {
        const quote = source[index];
        const delimiter = source.startsWith(quote.repeat(3), index)
          ? quote.repeat(3)
          : quote;
        let end = index + delimiter.length;
        while (end < source.length) {
          if (source.startsWith(delimiter, end)) {
            end += delimiter.length;
            break;
          }
          end += source[end] === "\\" ? 2 : 1;
        }
        output += token("string", source.slice(index, end));
        index = end;
        continue;
      }

      if ((match = rest.match(/^@[A-Za-z_]\w*/))) {
        output += token("meta", match[0]);
        index += match[0].length;
        continue;
      }

      if ((match = rest.match(/^(?:0[xX][\dA-Fa-f](?:_?[\dA-Fa-f])*|0[bB][01](?:_?[01])*|(?:\d(?:_?\d)*)?(?:\.\d(?:_?\d)*)?(?:[eE][+-]?\d(?:_?\d)*)?j?)/)) && match[0]) {
        output += token("number", match[0]);
        index += match[0].length;
        continue;
      }

      if ((match = rest.match(/^[A-Za-z_]\w*/))) {
        const word = match[0];
        let kind = null;
        if (keywords.has(word)) kind = "keyword";
        else if (literals.has(word)) kind = "literal";
        else if (builtins.has(word)) kind = "built_in";
        else if (/^(?:class|def)\s+$/.test(source.slice(Math.max(0, index - 10), index))) kind = "title";
        output += kind ? token(kind, word) : escapeHtml(word);
        index += word.length;
        continue;
      }

      if ((match = rest.match(/^(?:\*\*|\/\/|:=|==|!=|<=|>=|->|[-+*/%@&|^~<>:=])/))) {
        output += token("operator", match[0]);
        index += match[0].length;
        continue;
      }

      output += escapeHtml(source[index]);
      index += 1;
    }

    return output;
  }

  document.querySelectorAll("pre code.language-python").forEach((block) => {
    block.innerHTML = highlightPython(block.textContent);
    block.classList.add("hljs");
  });
})();
