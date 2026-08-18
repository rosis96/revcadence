/* The floating strip beside the active card.

   It is rendered inside the active card's wrapper and pinned to its right edge,
   so it follows the card without anyone measuring scroll offsets.

   Two of Google's six actions have nothing behind them in our schema: a form has
   questions and sections, not media blocks. Those buttons are present and
   disabled with a tooltip saying so — a clone that quietly drops them would read
   as finished when it is not, and one that pretends to work would be worse. */
import { Image as ImageIcon, Import, PlusCircle, SeparatorHorizontal, Type, Video } from "lucide-react";

export function AddRail({ onAddQuestion, onImport, onAddTitleBlock, onAddSection, disabled = false }) {
  const actions = [
    { key: "question", icon: PlusCircle, label: "Add question", run: onAddQuestion },
    { key: "import", icon: Import, label: "Import questions from another form", run: onImport },
    { key: "title", icon: Type, label: "Add title and description", run: onAddTitleBlock },
    { key: "image", icon: ImageIcon, label: "Add image — needs a media block on the form schema",
      run: null },
    { key: "video", icon: Video, label: "Add video — needs a media block on the form schema",
      run: null },
    { key: "section", icon: SeparatorHorizontal, label: "Add section", run: onAddSection },
  ];

  return (
    <div className="gf-rail" role="toolbar" aria-label="Add to form" aria-orientation="vertical">
      {actions.map((action) => {
        const Icon = action.icon;
        return (
          <button key={action.key} type="button" className="gf-rail-btn" title={action.label}
            aria-label={action.label} disabled={disabled || !action.run}
            onClick={() => action.run?.()}>
            <Icon size={21} />
          </button>
        );
      })}
    </div>
  );
}
