export type Power = string;

export interface UserBrief {
  id: number;
  username: string;
  display_name: string;
  online?: boolean;
  is_admin?: boolean;
}

export interface GameResult {
  type: "solo" | "draw";
  powers: Power[];
}

export interface GameSummary {
  id: number;
  name: string;
  status: "forming" | "active" | "finished";
  phase: string | null;
  phase_label: string;
  deadline_at: string | null;
  deadline_minutes: number | null;
  player_count: number;
  my_power: Power | null;
  my_centers: number | null;
  needs_orders: boolean;
  result: GameResult | null;
  creator: UserBrief;
  updated_at: string;
  variant?: VariantBrief;
}

export interface VariantBrief {
  slug: string;
  name: string;
  builtin: boolean;
  players: number;
  victory?: number;
  status?: string;
}

export interface Player extends UserBrief {
  user_id: number;
  power: Power | null;
  ready: boolean;
  needs_orders: boolean;
  has_orders: boolean;
  draw_vote: boolean;
  online: boolean;
}

export interface BoardState {
  units: Record<string, string[]>;
  retreats: Record<string, Record<string, string[]>>;
  centers: Record<string, string[]>;
  influence: Record<string, string[]>;
  builds: Record<string, { count: number; homes: string[] }>;
  phase: string;
  phase_type?: string;
  phase_label: string;
  eliminated?: string[];
  victory?: number | null;
}

export interface HistoryPhase extends BoardState {
  orders: Record<string, string[]>;
  results: Record<string, string[]>;
  next_phase: string;
}

export interface GameDetail extends GameSummary {
  assignment: "random" | "choice";
  press: "full" | "public" | "none";
  invite_code: string | null;
  is_creator: boolean;
  is_member: boolean;
  server_time: string;
  powers: Power[];
  players: Player[];
  board?: BoardState;
  history?: string[];
  my_orders?: string[];
  possible_orders?: Record<string, string[]>;
  ready?: boolean;
  draw_vote?: boolean;
}

export interface Message {
  id: number;
  sender: string;
  recipient: string;
  body: string;
  phase: string;
  created_at: string;
}

export interface FriendItem {
  id: number;
  user: UserBrief;
}

export interface FriendsList {
  friends: FriendItem[];
  incoming: FriendItem[];
  outgoing: FriendItem[];
}

export interface Invite {
  id: number;
  game: GameSummary;
  inviter: UserBrief;
}

export interface VariantInfo {
  slug: string;
  name: string;
  description: string;
  builtin: boolean;
  status: "builtin" | "approved" | "pending" | "rejected";
  players: number;
  powers: { name: string; adjective: string; color: string }[];
  victory: number;
  supply_centers: number;
  author: UserBrief | null;
  rules_text: string;
  updated_at?: string;
  review_note?: string | null;
}

export interface AdjacencyItem {
  a: string;
  b: string;
  type: "both" | "army" | "fleet";
}

export interface MapReport {
  errors: string[];
  warnings: string[];
  adjacency?: AdjacencyItem[];
  stats?: Record<string, number | string>;
}

export interface AIChange {
  id: number;
  op: string;
  a?: string;
  b?: string;
  type?: string;
  code?: string;
  value?: boolean | number;
  rule: string;
  explanation: string;
  applied?: boolean;
}

export interface VariantDetail extends VariantInfo {
  source_format?: "png" | "svg";
  has_image: boolean;
  report?: MapReport;
  version?: number;
  created_at?: string;
  can_manage: boolean;
  can_review: boolean;
  games?: number;
  ai?: { summary?: string; changes?: AIChange[]; unenforceable?: { rule: string; explanation: string }[]; error?: string; model?: string } | null;
  ai_enabled?: boolean;
}
