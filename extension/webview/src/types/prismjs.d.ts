declare module "prismjs" {
  type GrammarToken = Record<string, unknown>;
  interface PrismStatic {
    languages: Record<string, GrammarToken | undefined>;
    highlight(text: string, grammar: GrammarToken, language: string): string;
  }

  const Prism: PrismStatic;
  export = Prism;
}

declare module "prismjs/components/prism-bash";
declare module "prismjs/components/prism-css";
declare module "prismjs/components/prism-diff";
declare module "prismjs/components/prism-javascript";
declare module "prismjs/components/prism-json";
declare module "prismjs/components/prism-jsx";
declare module "prismjs/components/prism-markdown";
declare module "prismjs/components/prism-python";
declare module "prismjs/components/prism-tsx";
declare module "prismjs/components/prism-typescript";
declare module "prismjs/components/prism-yaml";
