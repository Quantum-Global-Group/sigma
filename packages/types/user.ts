export type APIKeyItem = {
  id: string;
  key_prefix: string;
  name: string | null;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked: boolean;
};

export type CreateKeyResponse = APIKeyItem & { raw_key: string };
