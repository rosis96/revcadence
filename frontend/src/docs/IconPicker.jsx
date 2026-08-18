// Icon picker for pages and folders.
//
// Deliberately a curated set, not all of lucide. `import * as Icons` would defeat
// tree-shaking and pull ~1,500 icons (megabytes) into the bundle for a control
// used twice. These 90 cover the vocabulary a revenue workspace actually needs,
// and each is a normal named import so the bundler keeps only what is used.
//
// Icon names are stored on Page.icon as their lucide export name, so adding to
// this list later needs no migration — an unknown name simply falls back.
import { useMemo, useRef, useState } from "react";
import { InlinePopup } from "../components";
import {
  Activity, AlertTriangle, Archive, Award, BarChart3, BookOpen, Bookmark, Bot, Box,
  Briefcase, Building2, Calendar, Camera, CheckCircle2, ClipboardList, Clock, Compass,
  Cpu, CreditCard, Crosshair, Database, DollarSign, Eye, FileText, Filter, Flag, Flame,
  Folder, FolderOpen, FolderTree, Gauge, Gavel, GitBranch, Globe, GraduationCap,
  Hammer, Handshake, Hash, Heart, HelpCircle, Image, Inbox, Info, Key, Layers, Library,
  Lightbulb, Link2, ListChecks, Lock, Mail, Map, Medal, Megaphone, MessageSquare,
  MessagesSquare, Network, NotebookPen, Package, Palette, PenLine, Phone, PieChart,
  Puzzle, Quote, Receipt, Rocket, Route, Scale, Search, Send, Server, Settings, Share2,
  Shield, ShieldCheck, ShoppingCart, SlidersHorizontal, Sparkles, Star, Tag, Target,
  ThumbsUp, TrendingUp, Trophy, User, Users, Video, Workflow, Wrench, Zap,
} from "lucide-react";

// name -> component. The name is what persists; the component is a render detail.
export const ICONS = {
  FileText, Folder, FolderOpen, FolderTree, Target, Crosshair, Users, User, Building2,
  Briefcase, Mail, Send, Inbox, Megaphone, Lightbulb, Rocket, Flag, Map, Compass, Route,
  Calendar, Clock, CheckCircle2, ListChecks, ClipboardList, BookOpen, Library,
  GraduationCap, NotebookPen, PenLine, Quote, Hash, Tag, Bookmark, Star, Heart, Sparkles,
  Zap, Flame, TrendingUp, BarChart3, PieChart, Gauge, Activity, Database, Server, Globe,
  Link2, Share2, Shield, ShieldCheck, Lock, Key, Settings, SlidersHorizontal, Wrench,
  Hammer, Puzzle, Layers, Box, Package, Archive, GitBranch, Workflow, Network, Cpu, Bot,
  MessageSquare, MessagesSquare, Phone, Video, Image, Camera, Palette, ShoppingCart,
  CreditCard, DollarSign, Receipt, Scale, Gavel, Handshake, Trophy, Award, Medal,
  ThumbsUp, AlertTriangle, Info, HelpCircle, Search, Filter, Eye,
};

// Split "FolderTree" into "folder tree" so search matches how people type.
const words = (name) => name.replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase();

/** Render a stored icon name. Falls back when the name is empty or unknown, so a
 *  page saved with an icon we later drop still renders. */
export function PageIcon({ name, fallback: Fallback = FileText, size = 14 }) {
  const Ic = ICONS[name] || Fallback;
  return <Ic size={size} />;
}

export default function IconPicker({ value, onChange, fallback = FileText }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const btnRef = useRef(null);
  const popRef = useRef(null);
  const names = useMemo(() => {
    const all = Object.keys(ICONS);
    if (!q.trim()) return all;
    const needle = q.trim().toLowerCase();
    return all.filter((n) => words(n).includes(needle));
  }, [q]);

  // Picking the icon that is already selected clears it — that is why there is no
  // separate clear button cluttering the header.
  const pick = (n) => { onChange(n === value ? "" : n); setOpen(false); };

  return (
    <div className="icon-picker">
      <button type="button" ref={btnRef} className="icon-pick-btn" onClick={() => setOpen((v) => !v)}
        title="Choose an icon" aria-expanded={open}>
        <PageIcon name={value} fallback={fallback} size={17} />
      </button>

      {/* Portals to <body>. Inside the dialog it was being clipped and scrolled by
          the dialog's own overflow, which is what pushed it off the edge. */}
      <InlinePopup open={open} onClose={() => setOpen(false)} anchorRef={btnRef}
        contentRef={popRef} className="icon-pop" side="auto">
        <div className="icon-pop-head">
          <input autoFocus value={q} placeholder="Search icons…"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setOpen(false)} />
        </div>
        <div className="icon-pop-grid">
          {names.map((n) => {
            const Ic = ICONS[n];
            return (
              <button type="button" key={n} title={words(n)}
                className={`icon-cell ${n === value ? "on" : ""}`} onClick={() => pick(n)}>
                <Ic size={16} />
              </button>
            );
          })}
          {!names.length && <p className="icon-pop-none">No icon matches “{q}”.</p>}
        </div>
      </InlinePopup>
    </div>
  );
}
