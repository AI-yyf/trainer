import type { Break, Parent, Root, Text } from "mdast";

/**
 * Chat replies use single newlines as intentional line breaks, while CommonMark
 * collapses them into spaces. Split text nodes on `\n` into `break` nodes so the
 * model's line structure survives without enabling raw HTML. Code, math and
 * table cell values live in leaf `value` fields, so they are untouched.
 */
export function remarkChatBreaks() {
  return (tree: Root): void => {
    const visit = (node: Root | Parent): void => {
      const children = node.children;
      if (!Array.isArray(children)) {
        return;
      }
      const next: Parent["children"] = [];
      for (const child of children) {
        if (child.type === "text" && child.value.includes("\n")) {
          const parts = child.value.split("\n");
          for (const [index, part] of parts.entries()) {
            if (index > 0) {
              next.push({ type: "break" } as Break);
            }
            if (part) {
              next.push({ ...(child as Text), value: part });
            }
          }
          continue;
        }
        visit(child as Parent);
        next.push(child);
      }
      node.children = next;
    };
    visit(tree);
  };
}
