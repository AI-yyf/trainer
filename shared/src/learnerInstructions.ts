/** Text that belongs to the learner, excluding quoted material and code examples. */
export function learnerInstructionText(message: string): string {
  let fence: { marker: string; length: number } | undefined;
  return message.split(/\r?\n/u).filter((line) => {
    if (/^\s*>|^(?: {4}|\t)/u.test(line)) return false;
    const marker = /^\s{0,3}(`{3,}|~{3,})(.*)$/u.exec(line);
    if (fence) {
      if (marker && marker[1][0] === fence.marker && marker[1].length >= fence.length && !marker[2].trim()) {
        fence = undefined;
      }
      return false;
    }
    if (marker) {
      fence = { marker: marker[1][0], length: marker[1].length };
      return false;
    }
    return true;
  }).join("\n");
}

/**
 * Only action clauses may dispatch a local operation. A refusal or a question
 * about an operation is still sent to the coach as ordinary conversation.
 * Filter clauses separately so "don't change the plan, give me an exercise"
 * preserves the second request.
 */
export function learnerActionText(message: string): string {
  return learnerInstructionText(message)
    .replace(/[「『“][^\n]*?[」』”]|"[^"\n]*"|(?<![A-Za-z0-9])'[^'\n]*'(?![A-Za-z0-9])|`[^`\n]+`/gu, "")
    .split(/[，,;；。!?！？\n]+/u)
    .map((clause) => clause.trim().replace(/^(?:(?:然后|再|并且?|但是|而是)|(?:and then|then|and|but|instead)\b)\s*/iu, ""))
    .filter((clause) => clause && !/^(?:(?:请(?:你)?|请问|帮我|麻烦(?:你)?|能不能|能否|可以|please|(?:can|could|would) you)\s*)*(?:我(?:现在|暂时|目前)?(?:不想|不需要|不要|不用)|不要|不用|无需|别|先别|暂不|不想|不需要|解释|说明|讨论|如何|怎么|怎样|为什么|如果|假如|只(?:想|需|要)?(?:解释|讨论)|do not\b|don['’]t\b|never\b|i (?:do not|don['’]t) (?:want|need)\b|how\b|why\b|what\b|explain\b|discuss\b|if\b)/iu.test(clause))
    .join(", ");
}

const NON_LEARNING_PLAN_CLAUSE =
  /(?:测试|迁移|发布|部署|上线|回滚|重构|执行|应急|项目|排期|开发|营销|商业|运营|扩容|升级|灾备)计划|\b(?:test|testing|migration|release|deployment|rollout|rollback|execution|refactoring|project|sprint|business|marketing|incident|recovery|capacity|upgrade)\s+plan\b/iu;
const EXPLICIT_LEARNING_PLAN_CONTEXT =
  /学习|训练|课程|教学|正式计划|阶段计划|save_formal_plan|\b(?:learning|study|training|curriculum|course|formal)\s+plan\b/iu;

/** Explicit plan requests share one vocabulary across the composer and host. */
export function requestsLearningPlanChange(message: string): boolean {
  const text = learnerActionText(message.replace(/^\/plan\b/iu, ""));
  return text.split(/, /u).some((clause) => {
    if (NON_LEARNING_PLAN_CLAUSE.test(clause) && !EXPLICIT_LEARNING_PLAN_CONTEXT.test(clause)) {
      return false;
    }
    return (
      /^(?:(?:请(?:你)?|帮我|麻烦(?:你)?|请问|能不能|能否|可以|可不可以)\s*)*(?:明确|直接|立即)?(?:重新)?(?:制定|生成|创建|调整|修改|修正|修复|补齐|更新|重写|保存)[^。！？\n]{0,90}计划/u.test(clause) ||
      /^(?:please\s+|(?:can|could|would) you\s+)*(?:create|make|generate|update|revise|adjust|fix|rewrite|repair|complete|save)\b.{0,90}\bplan\b/iu.test(clause) ||
      /^(?:(?:请(?:你)?|帮我)\s*)*(?:立即|直接)?调用\s*save_formal_plan\b/iu.test(clause)
    );
  });
}
