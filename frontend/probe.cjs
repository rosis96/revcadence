const t = require("tldraw");
const want = ["Tldraw","toRichText","useValue","DefaultFillStyle","DefaultColorStyle",
  "createShapeId","getSnapshot","loadSnapshot","DefaultDashStyle","DefaultSizeStyle",
  "DefaultFontStyle","track","useEditor"];
for (const n of want) console.log(n.padEnd(20), typeof t[n]);
