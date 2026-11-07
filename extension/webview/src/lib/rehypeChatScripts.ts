import type { Element, Root, Text } from "hast";
import type { Parent } from "unist";

const SCRIPT_PATTERN = /(\^[^\s^<>]{1,16}\^|~[^\s~<>/\\:]{1,16}~)/g;

type Child = Parent["children"][number];

function isParent(node: Child | Root): node is Parent {
  return Array.isArray((node as Parent).children);
}

function classNameOf(node: Element): string[] {
  const value: unknown = node.properties?.className;
  if (typeof value === "string") {
    return value.split(/\s+/);
  }
  return Array.isArray(value) ? value.map(String) : [];
}

function scriptElement(marker: "^" | "~", value: string): Element {
  return {
    type: "element",
    tagName: marker === "^" ? "sup" : "sub",
    properties: {},
    children: [{ type: "text", value }],
  };
}

function transformText(value: string): Array<Text | Element> {
  const parts = value.split(SCRIPT_PATTERN);
  if (parts.length === 1) {
    return [{ type: "text", value }];
  }
  const nodes: Array<Text | Element> = [];
  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith("^") && part.endsWith("^") && part.length > 2) {
      nodes.push(scriptElement("^", part.slice(1, -1)));
    } else if (part.startsWith("~") && part.endsWith("~") && part.length > 2) {
      nodes.push(scriptElement("~", part.slice(1, -1)));
    } else {
      nodes.push({ type: "text", value: part });
    }
  }
  return nodes;
}

/**
 * Chat replies often use ^sup^ / ~sub~ for prose scripts (x^2^, H~2~O).
 * Markdown has no standard syntax, so promote only short, delimiter-safe
 * runs into real <sup>/<sub> elements. Code, pre and KaTeX subtrees are
 * skipped; fenced code and display math keep their bytes.
 */
export function rehypeChatScripts() {
  return (tree: Root): void => {
    const visit = (node: Root | Parent): void => {
      const children = node.children;
      if (!Array.isArray(children)) return;
      const next: Parent["children"] = [];
      for (const child of children) {
        if (child.type === "element") {
          const element = child as Element;
          const tag = element.tagName;
          const classes = classNameOf(element);
          if (tag === "code" || tag === "pre" || classes.includes("katex")) {
            next.push(element);
            continue;
          }
          visit(element);
          next.push(element);
          continue;
        }
        if (child.type === "text") {
          next.push(...transformText((child as Text).value));
          continue;
        }
        if (isParent(child)) {
          visit(child);
        }
        next.push(child);
      }
      node.children = next;
    };
    visit(tree);
  };
}
