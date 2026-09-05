export type TrainingReturnMode = "result" | "blocker";

export type TrainingReturnSource = "training_bridge";

export interface TrainingReturnPayload {
  cardId: string;
  cardType: "practice" | "flash";
  cardTitle: string;
  returnMode: TrainingReturnMode;
  summary: string;
  verifiedResult?: string;
  blocker?: string;
  source: TrainingReturnSource;
}
