// The Scriptable script for the home screen widget, with this app's address and the widget key filled in.
// Scriptable (a free iPhone app) runs it to draw the widget. iOS decides when widgets refresh, roughly every
// 15 to 30 minutes, so the widget asks again after 15 and shows the last numbers it got when there's no signal.

const TEMPLATE = `// Creed food widget for Scriptable. Today's calories and protein against your targets.
// Made in Creed's Settings. The key only reads today's food totals. Turn the widget off there to stop it.
// icon-color: deep-gray; icon-glyph: utensils;

const CREED = "__CREED__";
const KEY = "__KEY__";
const REFRESH_MINUTES = 15;

const BG = new Color("#08080A");
const INK = new Color("#FFFFFF");
const INK2 = new Color("#B9B9C2");
const INK3 = new Color("#92929C");
const TRACK = new Color("#2A2A30");
const PROTEIN = new Color("#A78BFA");
const ATTENTION = new Color("#FF3B47");

const files = FileManager.local();
const cachePath = files.joinPath(files.documentsDirectory(), "creed-food-widget.json");

async function fetchFood() {
  const request = new Request(CREED + "/api/widget/food");
  request.headers = { Authorization: "Bearer " + KEY, Accept: "application/json" };
  request.timeoutInterval = 20;
  let body;
  try {
    body = await request.loadJSON();
  } catch (e) {
    return { offline: true };
  }
  const status = request.response ? request.response.statusCode : 0;
  if (status === 401) return { off: true };
  if (status !== 200 || !body || !body.date) return { offline: true };
  body.fetched = Date.now();
  files.writeString(cachePath, JSON.stringify(body));
  return { data: body };
}

function cached() {
  if (!files.fileExists(cachePath)) return null;
  try {
    return JSON.parse(files.readString(cachePath));
  } catch (e) {
    return null;
  }
}

const num = (n) => (n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-IN"));
const colorOf = (id) => (id === "protein" ? PROTEIN : INK);
const dayLabel = (type) => (type === "training" ? "Training day" : "Rest day");

function clock(ms) {
  const format = new DateFormatter();
  format.useNoDateStyle();
  format.useShortTimeStyle();
  return format.string(new Date(ms));
}

function shape(data) {
  const rings = data.rings || [];
  const kcal = rings.find((r) => r.id === "kcal") ||
    { id: "kcal", name: "Calories", unit: "kcal", eaten: data.kcal_eaten, target: null };
  return { kcal, others: rings.filter((r) => r.id !== "kcal") };
}

const fraction = (r) => (r.target ? r.eaten / r.target : 0);

function arc(ctx, centre, radius, upTo, color, width) {
  const steps = Math.max(2, Math.ceil(120 * upTo));
  const points = [];
  for (let i = 0; i <= steps; i++) {
    const angle = -Math.PI / 2 + 2 * Math.PI * upTo * (i / steps);
    points.push(new Point(centre + radius * Math.cos(angle), centre + radius * Math.sin(angle)));
  }
  const path = new Path();
  path.addLines(points);
  ctx.addPath(path);
  ctx.setStrokeColor(color);
  ctx.setLineWidth(width);
  ctx.strokePath();
}

// A ring like the app's, with the amount eaten in the middle and what it's out of beneath.
function ring(item, size, width, track) {
  const ctx = new DrawContext();
  ctx.size = new Size(size, size);
  ctx.opaque = false;
  ctx.respectScreenScale = true;
  const centre = size / 2;
  const radius = (size - width) / 2;
  arc(ctx, centre, radius, 1, track || TRACK, width);
  const done = Math.min(Math.max(fraction(item), 0), 1);
  if (done > 0) arc(ctx, centre, radius, done, colorOf(item.id), width);
  ctx.setTextAlignedCenter();
  ctx.setTextColor(INK);
  ctx.setFont(Font.boldRoundedSystemFont(size * 0.24));
  ctx.drawTextInRect(num(item.eaten), new Rect(0, size * 0.3, size, size * 0.3));
  ctx.setTextColor(INK2);
  ctx.setFont(Font.mediumSystemFont(size * 0.12));
  const under = item.target ? "of " + num(item.target) : item.unit;
  ctx.drawTextInRect(under, new Rect(0, size * 0.56, size, size * 0.16));
  return ctx.getImage();
}

function bar(item, width, height) {
  const ctx = new DrawContext();
  ctx.size = new Size(width, height);
  ctx.opaque = false;
  ctx.respectScreenScale = true;
  const rounded = (w, color) => {
    const path = new Path();
    path.addRoundedRect(new Rect(0, 0, w, height), height / 2, height / 2);
    ctx.addPath(path);
    ctx.setFillColor(color);
    ctx.fillPath();
  };
  rounded(width, TRACK);
  const done = Math.min(Math.max(fraction(item), 0), 1);
  if (done > 0) rounded(Math.max(height, width * done), colorOf(item.id));
  return ctx.getImage();
}

function addText(stack, text, size, color, weight) {
  const line = stack.addText(text);
  line.font = weight === "bold" ? Font.boldSystemFont(size) : weight === "semibold"
    ? Font.semiboldSystemFont(size) : Font.mediumSystemFont(size);
  line.textColor = color;
  line.lineLimit = 1;
  line.minimumScaleFactor = 0.6;
  return line;
}

function header(widget, data, stale) {
  const row = widget.addStack();
  row.centerAlignContent();
  addText(row, dayLabel(data.day_type).toUpperCase(), 11, INK3, "bold");
  row.addSpacer();
  addText(row, (stale ? "As of " : "") + clock(data.fetched), 11, stale ? ATTENTION : INK3, "medium");
}

function small(widget, data, stale) {
  const { kcal, others } = shape(data);
  header(widget, data, stale);
  widget.addSpacer();
  const rings = widget.addStack();
  rings.centerAlignContent();
  rings.addImage(ring(kcal, 64, 7));
  const protein = others.find((r) => r.id === "protein");
  if (protein) {
    rings.addSpacer(8);
    rings.addImage(ring(protein, 64, 7));
  }
  widget.addSpacer(6);
  const labels = widget.addStack();
  addText(labels, "kcal", 11, INK2, "semibold");
  if (protein) {
    labels.addSpacer();
    addText(labels, "protein g", 11, PROTEIN, "semibold");
  }
  widget.addSpacer();
}

function medium(widget, data, stale) {
  const { kcal, others } = shape(data);
  header(widget, data, stale);
  widget.addSpacer();
  const body = widget.addStack();
  body.centerAlignContent();
  const left = body.addStack();
  left.layoutVertically();
  left.addImage(ring(kcal, 92, 9));
  body.addSpacer(16);
  const right = body.addStack();
  right.layoutVertically();
  const list = others.length ? others.slice(0, 3) : [];
  if (!list.length) addText(right, kcal.target ? "Calories" : "Set targets in Creed's Food tab", 13, INK2, "semibold");
  list.forEach((item, i) => {
    if (i) right.addSpacer(8);
    const row = right.addStack();
    addText(row, item.name, 12, item.id === "protein" ? PROTEIN : INK2, "semibold");
    row.addSpacer();
    addText(row, num(item.eaten) + " / " + num(item.target) + " " + item.unit, 12, INK, "semibold");
    right.addSpacer(4);
    right.addImage(bar(item, 170, 5));
  });
  widget.addSpacer();
}

function circular(widget, data) {
  widget.addAccessoryWidgetBackground = true;
  widget.addImage(ring(shape(data).kcal, 60, 6, new Color("#FFFFFF", 0.25)));
}

function rectangular(widget, data) {
  const { kcal, others } = shape(data);
  const protein = others.find((r) => r.id === "protein");
  addText(widget, num(kcal.eaten) + (kcal.target ? " / " + num(kcal.target) : "") + " kcal", 15, INK, "bold");
  if (protein) addText(widget, "Protein " + num(protein.eaten) + " / " + num(protein.target) + " g", 13, INK, "medium");
  widget.addSpacer(4);
  widget.addImage(bar(kcal, 140, 5));
}

function inline(widget, data) {
  const { kcal, others } = shape(data);
  const protein = others.find((r) => r.id === "protein");
  let text = num(kcal.eaten) + (kcal.target ? "/" + num(kcal.target) : "") + " kcal";
  if (protein) text += " · " + num(protein.eaten) + "/" + num(protein.target) + " g protein";
  widget.addText(text);
}

function message(widget, text) {
  addText(widget, "CREED FOOD", 11, INK3, "bold");
  widget.addSpacer(6);
  const line = widget.addText(text);
  line.font = Font.mediumSystemFont(13);
  line.textColor = INK2;
  line.minimumScaleFactor = 0.7;
}

async function build(family) {
  const widget = new ListWidget();
  const lockScreen = family && family.startsWith("accessory");
  if (!lockScreen) {
    widget.backgroundColor = BG;
    widget.setPadding(14, 14, 14, 14);
  }
  widget.url = CREED + "/#/food";
  widget.refreshAfterDate = new Date(Date.now() + REFRESH_MINUTES * 60 * 1000);

  const result = await fetchFood();
  if (result.off) {
    message(widget, lockScreen ? "Widget off" : "This widget is off. Turn it on in Creed's Settings and paste the new script.");
    return widget;
  }
  const data = result.data || cached();
  if (!data) {
    message(widget, "Can't reach Creed. It'll try again soon.");
    return widget;
  }
  const stale = !result.data;
  if (family === "accessoryCircular") circular(widget, data);
  else if (family === "accessoryRectangular") rectangular(widget, data);
  else if (family === "accessoryInline") inline(widget, data);
  else if (family === "small") small(widget, data, stale);
  else medium(widget, data, stale);
  return widget;
}

const widget = await build(config.widgetFamily);
if (config.runsInWidget) Script.setWidget(widget);
else await widget.presentMedium();
Script.complete();
`;

/** The script to paste into Scriptable. The address and key are plain strings, so quote-safe characters only. */
export function widgetScript(origin, key) {
  const safe = (value) => String(value).replace(/[^A-Za-z0-9:/._\-]/g, '');
  return TEMPLATE.replace('__CREED__', safe(origin.replace(/\/$/, ''))).replace('__KEY__', safe(key));
}
