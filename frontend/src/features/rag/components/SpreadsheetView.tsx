import type { Evidence } from "../api";
import type { SpreadsheetPage } from "../useDocumentPage";

export default function SpreadsheetView({
  document: doc,
  evidence,
  onPage,
}: {
  document: SpreadsheetPage;
  evidence: Evidence;
  onPage: (page: number, sheet: string) => void;
}) {
  return (
    <div className="rag-spreadsheet">
      <div className="rag-sheet-tabs" role="tablist" aria-label="엑셀 시트">
        {doc.sheets.map((sheet) => (
          <button
            key={sheet.name}
            role="tab"
            aria-selected={doc.sheet === sheet.name}
            onClick={() => onPage(0, sheet.name)}
          >
            {sheet.name}
            <small>{sheet.rows}행</small>
          </button>
        ))}
      </div>
      <div className="rag-document-pagination">
        <button
          disabled={doc.previous_page === null}
          onClick={() => onPage(doc.previous_page!, doc.sheet)}
        >
          이전 행
        </button>
        <span>
          {doc.sheet} · {doc.rows[0]?.row || 0}–{doc.rows.at(-1)?.row || 0}행 ·{" "}
          {doc.page + 1}/{doc.total_pages}
        </span>
        <button
          disabled={doc.next_page === null}
          onClick={() => onPage(doc.next_page!, doc.sheet)}
        >
          다음 행
        </button>
      </div>
      <div
        className="rag-sheet-grid"
        tabIndex={0}
        aria-label={`${doc.sheet} 원문 표`}
      >
        <table>
          <thead>
            <tr>
              <th aria-label="행 번호" />
              {doc.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {doc.rows.map((row) => (
              <tr
                key={row.row}
                className={
                  evidence.location.sheet === doc.sheet &&
                  row.row >= (evidence.location.start_row || 0) &&
                  row.row <= (evidence.location.end_row || 0)
                    ? "highlight"
                    : ""
                }
              >
                <th>{row.row}</th>
                {doc.columns.map((column) => {
                  const cell = row.cells.find(
                    (c) => c.address === column + row.row,
                  );
                  return (
                    <td
                      key={column}
                      title={
                        cell
                          ? `${cell.address}${cell.formula ? ` · ${cell.formula}` : ""}`
                          : ""
                      }
                    >
                      {cell?.display != null
                        ? String(cell.display)
                        : cell?.value != null
                          ? String(cell.value)
                          : ""}
                      {cell?.formula && (
                        <small className="rag-cell-formula">
                          {cell.value == null
                            ? `${cell.formula} · 저장된 계산 결과 없음`
                            : "ƒ · 저장된 계산값"}
                        </small>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="rag-footnote">
        수식의 값은 파일을 저장한 시점 기준입니다.
        {doc.truncated ? " 긴 셀 내용은 일부만 표시합니다." : ""}
      </p>
    </div>
  );
}
