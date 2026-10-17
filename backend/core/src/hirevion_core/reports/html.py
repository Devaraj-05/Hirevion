"""A report document as a standalone HTML page, for the PDF (SP-17; ADR-0023).

The page has no script, no external request and no form: a strict content-security policy says so
and the renderer also blocks every request. Jinja2's autoescape handles every string, and the
template never marks one safe, so a candidate's words (a transcript, a note, a process name) can't
inject markup into a report."""

from __future__ import annotations

from jinja2 import Environment

from hirevion_core.reports.blocks import Document

CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'"

STYLE = """
@page { size: A4; margin: 18mm 14mm 20mm 14mm; }
* { box-sizing: border-box; }
body { font: 10pt/1.45 "Segoe UI", Inter, Arial, sans-serif; color: #111827; margin: 0; }
header.doc { border-bottom: 2px solid #111827; padding-bottom: 6mm; margin-bottom: 6mm; }
header.doc h1 { font-size: 20pt; margin: 0 0 2mm; }
header.doc p { margin: 0; color: #374151; }
.banner { display: inline-block; margin-top: 3mm; padding: 1mm 3mm; border: 1px solid #991b1b;
  color: #991b1b; font-weight: 600; font-size: 8.5pt; letter-spacing: .04em; }
nav.contents { margin: 0 0 6mm; padding: 3mm 4mm; background: #f3f4f6; }
nav.contents ol { margin: 1mm 0 0; padding-left: 5mm; columns: 2; }
section.part { margin: 0 0 7mm; }
section.part h2 { font-size: 13pt; margin: 0 0 2mm; padding-bottom: 1mm;
  border-bottom: 1px solid #d1d5db; break-after: avoid; }
.status { font-size: 8pt; font-weight: 600; text-transform: uppercase; letter-spacing: .05em;
  margin-left: 2mm; color: #6b7280; }
.status.pending { color: #92400e; }
p.note { color: #4b5563; font-style: italic; margin: 0 0 2mm; }
p, ul, ol, dl, table, pre, blockquote { margin: 0 0 3mm; }
p.muted { color: #6b7280; }
dl.facts { display: grid; grid-template-columns: 48mm 1fr; gap: 1mm 4mm; }
dl.facts dt { color: #4b5563; }
dl.facts dd { margin: 0; overflow-wrap: anywhere; }
table { width: 100%; border-collapse: collapse; font-size: 8.8pt; }
caption { text-align: left; font-weight: 600; padding-bottom: 1mm; break-after: avoid; }
th, td { border: 1px solid #d1d5db; padding: 1.2mm 2mm; text-align: left; vertical-align: top;
  overflow-wrap: anywhere; }
th { background: #f3f4f6; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
blockquote { border-left: 3px solid #9ca3af; padding: 0 0 0 3mm; color: #1f2937; }
blockquote cite { display: block; font-size: 8.3pt; color: #6b7280; font-style: normal; }
.notice { border: 1px solid #93c5fd; background: #eff6ff; padding: 2mm 3mm; }
.notice.warning { border-color: #fbbf24; background: #fffbeb; }
figure.code { margin: 0 0 3mm; }
figure.code figcaption { font-weight: 600; font-size: 8.8pt; }
pre { background: #f3f4f6; padding: 2mm 3mm; white-space: pre-wrap; overflow-wrap: anywhere;
  font: 8.5pt/1.4 Consolas, "Courier New", monospace; }
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{{ csp }}">
<title>{{ doc.title }} - {{ doc.subtitle }}</title>
<style>{{ style }}</style>
</head>
<body>
<header class="doc">
  <h1>{{ doc.title }}</h1>
  <p>{{ doc.subtitle }}</p>
  {% if doc.confidential %}<span class="banner">CONFIDENTIAL - INTERNAL USE ONLY</span>{% endif %}
</header>
{% if doc.sections | length > 1 %}
<nav class="contents" aria-label="Contents">
  <strong>Contents</strong>
  <ol>{% for item in doc.sections %}<li>{{ item.title }}</li>{% endfor %}</ol>
</nav>
{% endif %}
{% for item in doc.sections %}
<section class="part" id="{{ item.key }}">
  <h2>{{ item.title }}{% if item.status != "populated" %}<span class="status {{ item.status }}">{{ item.status }}</span>{% endif %}</h2>
  {% if item.note %}<p class="note">{{ item.note }}</p>{% endif %}
  {% for block in item.blocks %}
    {% if block.type == "text" %}
      <p{% if block.tone == "muted" %} class="muted"{% endif %}>{{ block.text }}</p>
    {% elif block.type == "list" %}
      <ul>{% for entry in block["items"] %}<li>{{ entry }}</li>{% endfor %}</ul>
    {% elif block.type == "facts" %}
      <dl class="facts">{% for row in block.rows %}<dt>{{ row.label }}</dt><dd>{{ row.value }}</dd>{% endfor %}</dl>
    {% elif block.type == "table" %}
      <table>
        <caption>{{ block.caption }}</caption>
        <thead><tr>{% for column in block.columns %}<th scope="col">{{ column }}</th>{% endfor %}</tr></thead>
        <tbody>
        {% for row in block.rows %}<tr>{% for cell in row %}<td>{{ cell }}</td>{% endfor %}</tr>
        {% else %}<tr><td colspan="{{ block.columns | length }}">Nothing to list.</td></tr>{% endfor %}
        </tbody>
      </table>
    {% elif block.type == "quotes" %}
      {% for entry in block["items"] %}<blockquote>&ldquo;{{ entry.text }}&rdquo;<cite>{{ entry.source }}</cite></blockquote>{% endfor %}
    {% elif block.type == "notice" %}
      <p class="notice {{ block.tone }}">{{ block.text }}</p>
    {% elif block.type == "code" %}
      <figure class="code">{% if block.caption %}<figcaption>{{ block.caption }}</figcaption>{% endif %}<pre>{{ block.text }}</pre></figure>
    {% endif %}
  {% endfor %}
</section>
{% endfor %}
</body>
</html>
"""  # noqa: E501

_environment = Environment(autoescape=True, trim_blocks=True)  # every string is escaped
_template = _environment.from_string(TEMPLATE)


def render_html(doc: Document) -> str:
    return _template.render(doc=doc, csp=CSP, style=STYLE)
