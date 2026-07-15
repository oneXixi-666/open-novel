import { diff_match_patch, DIFF_DELETE, DIFF_EQUAL, DIFF_INSERT } from "diff-match-patch";
import { Typography } from "antd";
import { authorText } from "../utils/authorText";

const { Paragraph } = Typography;
const dmp = new diff_match_patch();

export function DiffView({ baseText, candidateText }: { baseText: string; candidateText: string }) {
  const baseParagraphs = splitParagraphs(baseText);
  const candidateParagraphs = splitParagraphs(candidateText);
  const diffs = dmp.diff_main(baseParagraphs.join("\n"), candidateParagraphs.join("\n"));
  dmp.diff_cleanupSemantic(diffs);
  return (
    <div className="diff-view">
      {diffs.map(([type, text], index) => {
        const className = type === DIFF_INSERT ? "diff-insert" : type === DIFF_DELETE ? "diff-delete" : "diff-equal";
        if (type === DIFF_DELETE) {
          return null;
        }
        return (
          <Paragraph key={`${index}-${text.slice(0, 12)}`} className={className}>
            {type === DIFF_INSERT ? <strong>新增</strong> : null}
            {authorText(text)}
          </Paragraph>
        );
      })}
    </div>
  );
}

function splitParagraphs(text: string) {
  return text
    .split(/\r?\n+/)
    .map((item) => item.trim())
    .filter(Boolean);
}
