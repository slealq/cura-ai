'use client';

import { Fragment, useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { notFound } from 'next/navigation';
import { Loader2, Plus, Pencil, Trash2, RefreshCw, Eye, EyeOff, Key, ChevronRight, ChevronDown, Search } from 'lucide-react';
import { toast } from 'sonner';
import { billingApi, settingsApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { cn, formatDateCompact, formatNumber } from '@/lib/utils';
import type { AdminUserBalance, APIKeyInfo, BillingLogEntry, CostCatalogEntry, ModelBulkUpdateRequest } from '@/types';
import OperationsMonitor from './OperationsMonitor';

type DateRange = '7d' | '30d' | '90d' | 'all';

function getStartDate(range: DateRange): string | undefined {
  if (range === 'all') return undefined;
  const days = range === '7d' ? 7 : range === '30d' ? 30 : 90;
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

export default function AdminPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [dateRange, setDateRange] = useState<DateRange>('30d');
  const [creditUserId, setCreditUserId] = useState<number | null>(null);
  const [creditAmount, setCreditAmount] = useState('');
  const [creditDescription, setCreditDescription] = useState('');
  const [showCatalogForm, setShowCatalogForm] = useState(false);
  const [editingEntry, setEditingEntry] = useState<CostCatalogEntry | null>(null);
  const [catalogForm, setCatalogForm] = useState({
    provider: '',
    model: '',
    operation: '',
    cost_per_input_token: 0,
    cost_per_output_token: 0,
    cost_per_call: 0,
    platform_markup: 1.0,
    pricing_rules: '' as string,
  });
  const [activeTab, setActiveTab] = useState<'usage' | 'catalog' | 'logs' | 'operations' | 'system'>('usage');
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState('');
  const [showKeyInput, setShowKeyInput] = useState(false);

  // Model edit dialog state
  const [editingModel, setEditingModel] = useState<{ provider: string; model: string } | null>(null);
  const [modelEditForm, setModelEditForm] = useState<{
    cost_per_input_token: number;
    cost_per_output_token: number;
    cost_per_call: number;
    operations: { operation: string; platform_markup: number }[];
  }>({ cost_per_input_token: 0, cost_per_output_token: 0, cost_per_call: 0, operations: [] });
  const [setAllMarkup, setSetAllMarkup] = useState('');
  const [expandedTokenModels, setExpandedTokenModels] = useState<Set<string>>(new Set());

  // Billing Logs state
  const [logsPage, setLogsPage] = useState(0);
  const [logsUserSearch, setLogsUserSearch] = useState('');
  const [logsUserSearchInput, setLogsUserSearchInput] = useState('');
  const [logsProvider, setLogsProvider] = useState('');
  const [logsOperation, setLogsOperation] = useState('');
  const [logsDateRange, setLogsDateRange] = useState<DateRange>('30d');
  const [expandedLogId, setExpandedLogId] = useState<number | null>(null);

  const isAdmin = user?.role === 'admin';

  // 404 for non-admins
  if (user && user.role !== 'admin') {
    notFound();
  }

  const startDate = getStartDate(dateRange);

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['billing', 'admin', 'summary', dateRange],
    queryFn: () => billingApi.adminGetSummary(startDate),
  });

  const { data: users, isLoading: usersLoading } = useQuery({
    queryKey: ['billing', 'admin', 'users'],
    queryFn: billingApi.adminGetUsers,
  });

  const { data: catalog, isLoading: catalogLoading } = useQuery({
    queryKey: ['billing', 'admin', 'catalog'],
    queryFn: billingApi.adminGetCatalog,
  });

  const { data: apiKeys, isLoading: apiKeysLoading } = useQuery({
    queryKey: ['settings', 'api-keys'],
    queryFn: settingsApi.getApiKeys,
    enabled: isAdmin,
  });

  const logsStartDate = getStartDate(logsDateRange);
  const LOGS_LIMIT = 50;

  const { data: logsData, isLoading: logsLoading } = useQuery({
    queryKey: ['billing', 'admin', 'logs', logsPage, logsUserSearch, logsProvider, logsOperation, logsDateRange],
    queryFn: () => billingApi.adminGetLogs({
      skip: logsPage * LOGS_LIMIT,
      limit: LOGS_LIMIT,
      user_search: logsUserSearch || undefined,
      provider: logsProvider || undefined,
      operation: logsOperation || undefined,
      start_date: logsStartDate,
    }),
    enabled: activeTab === 'logs',
  });

  const saveKeyMutation = useMutation({
    mutationFn: ({ provider, key }: { provider: string; key: string }) =>
      settingsApi.saveApiKey(provider, key),
    onSuccess: () => {
      toast.success('API key saved and validated');
      queryClient.invalidateQueries({ queryKey: ['settings', 'api-keys'] });
      setEditingProvider(null);
      setKeyInput('');
      setShowKeyInput(false);
    },
    onError: () => toast.error('Failed to save API key'),
  });

  const validateKeyMutation = useMutation({
    mutationFn: (provider: string) => settingsApi.validateApiKey(provider),
    onSuccess: (data: APIKeyInfo) => {
      toast.success(`Key re-validated: ${data.status}`);
      queryClient.invalidateQueries({ queryKey: ['settings', 'api-keys'] });
    },
    onError: () => toast.error('Failed to validate API key'),
  });

  const deleteKeyMutation = useMutation({
    mutationFn: (provider: string) => settingsApi.deleteApiKey(provider),
    onSuccess: () => {
      toast.success('API key deleted');
      queryClient.invalidateQueries({ queryKey: ['settings', 'api-keys'] });
    },
    onError: () => toast.error('Failed to delete API key'),
  });

  const addCreditsMutation = useMutation({
    mutationFn: ({ userId, amount, description }: { userId: number; amount: number; description: string }) =>
      billingApi.adminAddCredits(userId, amount, description),
    onSuccess: () => {
      toast.success('Sparks added successfully');
      queryClient.invalidateQueries({ queryKey: ['billing'] });
      setCreditUserId(null);
      setCreditAmount('');
      setCreditDescription('');
    },
    onError: () => toast.error('Failed to add sparks'),
  });

  const saveCatalogMutation = useMutation({
    mutationFn: (entry: { id?: number } & typeof catalogForm) => {
      // Parse pricing_rules JSON string if provided
      let parsedRules: Record<string, unknown> | null = null;
      if (entry.pricing_rules && entry.pricing_rules.trim()) {
        try {
          parsedRules = JSON.parse(entry.pricing_rules);
        } catch {
          throw new Error('Invalid JSON in pricing rules');
        }
      }
      const payload = { ...entry, pricing_rules: parsedRules };
      if (entry.id) {
        return billingApi.adminUpdateCatalogEntry(entry.id, payload);
      }
      return billingApi.adminCreateCatalogEntry(payload);
    },
    onSuccess: () => {
      toast.success('Catalog entry saved');
      queryClient.invalidateQueries({ queryKey: ['billing', 'admin', 'catalog'] });
      setShowCatalogForm(false);
      setEditingEntry(null);
      setCatalogForm({ provider: '', model: '', operation: '', cost_per_input_token: 0, cost_per_output_token: 0, cost_per_call: 0, platform_markup: 1.0, pricing_rules: '' });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Failed to save catalog entry'),
  });

  const deleteCatalogMutation = useMutation({
    mutationFn: (id: number) => billingApi.adminDeleteCatalogEntry(id),
    onSuccess: () => {
      toast.success('Catalog entry deleted');
      queryClient.invalidateQueries({ queryKey: ['billing', 'admin', 'catalog'] });
    },
    onError: () => toast.error('Failed to delete catalog entry'),
  });

  const bulkUpdateMutation = useMutation({
    mutationFn: (data: ModelBulkUpdateRequest) => billingApi.adminBulkUpdateModel(data),
    onSuccess: () => {
      toast.success('Model pricing updated');
      queryClient.invalidateQueries({ queryKey: ['billing', 'admin', 'catalog'] });
      setEditingModel(null);
    },
    onError: () => toast.error('Failed to update model pricing'),
  });

  const sortedUsers = users?.slice().sort((a: AdminUserBalance, b: AdminUserBalance) => a.balance - b.balance) || [];

  // Categorize catalog entries by operation type
  type OperationCategory = 'vision' | 'language' | 'embedding' | 'generate' | 'generate_lora' | 'train' | 'edit' | 'other';

  const categoryLabels: Record<OperationCategory, string> = {
    vision: 'Vision',
    language: 'Language',
    embedding: 'Embedding',
    generate: 'Generate',
    generate_lora: 'Generate with LoRA',
    train: 'Train',
    edit: 'Edit',
    other: 'Other',
  };

  const categoryOrder: OperationCategory[] = ['vision', 'language', 'embedding', 'generate', 'generate_lora', 'train', 'edit', 'other'];

  function getOperationCategory(operation: string, model: string): OperationCategory {
    switch (operation) {
      case 'tag':
      case 'describe':
      case 'evaluate':
      case 'evaluate_creative':
        return 'vision';
      case 'summarize':
      case 'summarize_eval':
      case 'generate_prompts':
      case 'expand_prompt':
        return 'language';
      case 'embed':
        return 'embedding';
      case 'generate':
        return model.toLowerCase().includes('lora') ? 'generate_lora' : 'generate';
      case 'train':
        return 'train';
      case 'edit':
        return 'edit';
      default:
        return 'other';
    }
  }

  type ModelGroup = {
    provider: string;
    model: string;
    entries: CostCatalogEntry[];
    isTokenBased: boolean;
  };

  type CategoryGroup = {
    tokenModels: ModelGroup[];
    perCallEntries: CostCatalogEntry[];
  };

  const catalogByCategory = useMemo(() => {
    if (!catalog) return {} as Record<OperationCategory, CategoryGroup>;

    const result: Record<OperationCategory, CategoryGroup> = {} as Record<OperationCategory, CategoryGroup>;

    // Group entries by category, then within each category by provider::model
    catalog.forEach((entry: CostCatalogEntry) => {
      const cat = getOperationCategory(entry.operation, entry.model);
      if (!result[cat]) result[cat] = { tokenModels: [], perCallEntries: [] };

      const isTokenBased =
        (entry.cost_per_input_token && entry.cost_per_input_token > 0) ||
        (entry.cost_per_output_token && entry.cost_per_output_token > 0);

      if (isTokenBased) {
        // Group token-based entries by provider::model within the category
        const key = `${entry.provider}::${entry.model}`;
        let group = result[cat].tokenModels.find((g) => `${g.provider}::${g.model}` === key);
        if (!group) {
          group = { provider: entry.provider, model: entry.model, entries: [], isTokenBased: true };
          result[cat].tokenModels.push(group);
        }
        group.entries.push(entry);
      } else {
        result[cat].perCallEntries.push(entry);
      }
    });

    // Sort token models within each category
    Object.values(result).forEach((group) => {
      group.tokenModels.sort((a, b) => a.provider.localeCompare(b.provider) || a.model.localeCompare(b.model));
    });

    return result;
  }, [catalog]);

  return (
    <div className="p-6 space-y-8 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold">Admin</h1>
        <div className="flex gap-1 bg-muted rounded-lg p-1 mt-4 w-fit">
          {([
            { key: 'usage', label: 'Usage & Billing' },
            { key: 'catalog', label: 'Cost Catalog' },
            { key: 'logs', label: 'Billing Logs' },
            { key: 'operations', label: 'Operations' },
            { key: 'system', label: 'System' },
          ] as const).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={cn(
                'px-3 py-1 text-sm rounded-md transition-colors',
                activeTab === key ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* System Tab - Platform API Keys */}
      {activeTab === 'system' && (
      <section>
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <Key className="h-5 w-5" /> Platform API Keys
        </h2>
        {apiKeysLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {(apiKeys || []).map((info: APIKeyInfo) => {
              const providerLabels: Record<string, string> = { openai: 'OpenAI', anthropic: 'Anthropic', fal: 'fal.ai', sentry: 'Sentry' };
              const label = providerLabels[info.provider] || info.provider;
              const isSentry = info.provider === 'sentry';
              const isEditing = editingProvider === info.provider;

              const statusColor: Record<string, string> = {
                active: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
                invalid: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
                quota_exceeded: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
                env_var: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
                not_configured: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
                unknown: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
              };
              const statusLabel: Record<string, string> = {
                active: 'Active',
                invalid: 'Invalid',
                quota_exceeded: 'Quota Exceeded',
                env_var: 'Env Var',
                not_configured: 'Not Set',
                unknown: 'Unknown',
              };

              return (
                <div key={info.provider} className="bg-card border rounded-lg p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="font-medium">{label}</h3>
                    <span className={cn('px-2 py-0.5 rounded-full text-xs font-medium', statusColor[info.status] || statusColor.unknown)}>
                      {statusLabel[info.status] || info.status}
                    </span>
                  </div>

                  {info.key_suffix && (
                    <p className="text-sm text-muted-foreground font-mono">...{info.key_suffix}</p>
                  )}

                  {info.last_validated_at && (
                    <p className="text-xs text-muted-foreground">
                      Validated: {formatDateCompact(info.last_validated_at)}
                    </p>
                  )}

                  {info.last_error && info.status !== 'env_var' && (
                    <p className="text-xs text-red-500 truncate" title={info.last_error}>{info.last_error}</p>
                  )}

                  {isEditing ? (
                    <div className="space-y-2">
                      <div className="relative">
                        <input
                          type={isSentry || showKeyInput ? 'text' : 'password'}
                          value={keyInput}
                          onChange={(e) => setKeyInput(e.target.value)}
                          placeholder={isSentry ? 'https://<key>@<host>/<project_id>' : 'Enter API key...'}
                          className="w-full px-3 py-2 pr-9 bg-background border rounded-md text-sm font-mono"
                        />
                        {!isSentry && (
                          <button
                            type="button"
                            onClick={() => setShowKeyInput(!showKeyInput)}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          >
                            {showKeyInput ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          </button>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => {
                            if (!keyInput.trim()) {
                              toast.error('Please enter an API key');
                              return;
                            }
                            saveKeyMutation.mutate({ provider: info.provider, key: keyInput.trim() });
                          }}
                          disabled={saveKeyMutation.isPending}
                          className="flex-1 px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
                        >
                          {saveKeyMutation.isPending ? 'Validating...' : 'Save & Validate'}
                        </button>
                        <button
                          onClick={() => { setEditingProvider(null); setKeyInput(''); setShowKeyInput(false); }}
                          className="px-3 py-1.5 text-xs border rounded-md"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => { setEditingProvider(info.provider); setKeyInput(''); setShowKeyInput(false); }}
                        className="p-1.5 text-muted-foreground hover:text-foreground rounded-md hover:bg-muted"
                        title="Edit key"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      {info.status !== 'not_configured' && info.status !== 'env_var' && (
                        <>
                          <button
                            onClick={() => validateKeyMutation.mutate(info.provider)}
                            disabled={validateKeyMutation.isPending}
                            className="p-1.5 text-muted-foreground hover:text-foreground rounded-md hover:bg-muted disabled:opacity-50"
                            title="Re-validate"
                          >
                            <RefreshCw className={cn('h-3.5 w-3.5', validateKeyMutation.isPending && 'animate-spin')} />
                          </button>
                          <button
                            onClick={() => {
                              if (confirm(`Delete the stored ${label} key? Will fall back to env var if set.`)) {
                                deleteKeyMutation.mutate(info.provider);
                              }
                            }}
                            className="p-1.5 text-muted-foreground hover:text-red-500 rounded-md hover:bg-muted"
                            title="Delete key"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
      )}

      {/* Usage Tab - Platform Summary + User Balances */}
      {activeTab === 'usage' && (
      <>
      <div className="flex justify-end">
        <div className="flex gap-1 bg-muted rounded-lg p-1">
          {(['7d', '30d', '90d', 'all'] as DateRange[]).map((range) => (
            <button
              key={range}
              onClick={() => setDateRange(range)}
              className={cn(
                'px-3 py-1 text-sm rounded-md transition-colors',
                dateRange === range ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {range === 'all' ? 'All' : range}
            </button>
          ))}
        </div>
      </div>

      {/* Platform Summary */}
      <section>
        <h2 className="text-lg font-semibold mb-4">Platform Summary</h2>
        {summaryLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : summary ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm text-muted-foreground">Platform Cost</p>
                <p className="text-2xl font-bold">${formatNumber(summary.total_raw_cost)}</p>
              </div>
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm text-muted-foreground">Charged to Users</p>
                <p className="text-2xl font-bold">{formatNumber(summary.total_charged)} sparks</p>
              </div>
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm text-muted-foreground">Margin</p>
                <p className="text-2xl font-bold">${formatNumber(summary.margin)}</p>
              </div>
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm text-muted-foreground">API Calls</p>
                <p className="text-2xl font-bold">{summary.record_count}</p>
              </div>
            </div>

            {/* Provider breakdown */}
            {Object.keys(summary.by_provider).length > 0 && (
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm font-medium mb-3">By Provider</p>
                <div className="space-y-2">
                  {Object.entries(summary.by_provider)
                    .sort(([, a], [, b]) => b - a)
                    .map(([provider, cost]) => {
                      const pct = summary.total_charged > 0 ? (cost / summary.total_charged) * 100 : 0;
                      return (
                        <div key={provider} className="flex items-center gap-3">
                          <span className="text-sm w-20 text-muted-foreground">{provider}</span>
                          <div className="flex-1 bg-muted rounded-full h-2 overflow-hidden">
                            <div className="bg-primary h-full rounded-full" style={{ width: `${pct}%` }} />
                          </div>
                          <span className="text-sm font-medium w-24 text-right">{formatNumber(cost)} sparks</span>
                        </div>
                      );
                    })}
                </div>
              </div>
            )}

            {/* Operation breakdown */}
            {Object.keys(summary.by_operation).length > 0 && (
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm font-medium mb-3">By Operation</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {Object.entries(summary.by_operation)
                    .sort(([, a], [, b]) => b - a)
                    .map(([op, cost]) => (
                      <div key={op} className="bg-muted rounded-lg px-3 py-2">
                        <p className="text-xs text-muted-foreground">{op}</p>
                        <p className="text-sm font-medium">{cost.toFixed(4)}</p>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </div>
        ) : null}
      </section>

      {/* User Balances */}
      <section>
        <h2 className="text-lg font-semibold mb-4">User Balances</h2>
        {usersLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : (
          <div className="bg-card border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left px-4 py-3 font-medium">User</th>
                  <th className="text-right px-4 py-3 font-medium">Balance</th>
                  <th className="text-right px-4 py-3 font-medium">Total Spent</th>
                  <th className="text-right px-4 py-3 font-medium">Last Activity</th>
                  <th className="text-right px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedUsers.map((u: AdminUserBalance) => (
                  <tr key={u.user_id} className="border-b last:border-0">
                    <td className="px-4 py-3">
                      <p className="font-medium">{u.display_name || u.email}</p>
                      {u.display_name && <p className="text-xs text-muted-foreground">{u.email}</p>}
                    </td>
                    <td className={cn('text-right px-4 py-3 font-medium', u.balance < 10 && 'text-red-500')}>
                      {formatNumber(u.balance)}
                    </td>
                    <td className="text-right px-4 py-3">{formatNumber(u.total_spent)}</td>
                    <td className="text-right px-4 py-3 text-muted-foreground">
                      {u.last_activity ? formatDateCompact(u.last_activity) : '-'}
                    </td>
                    <td className="text-right px-4 py-3">
                      <button
                        onClick={() => {
                          setCreditUserId(u.user_id);
                          setCreditAmount('');
                          setCreditDescription('');
                        }}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-primary text-primary-foreground rounded hover:bg-primary/90"
                      >
                        <Plus className="h-3 w-3" /> Sparks
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Add Credits Dialog */}
        {creditUserId !== null && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setCreditUserId(null)}>
            <div className="bg-card border rounded-lg p-6 w-96 space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-semibold">Add Sparks</h3>
              <p className="text-sm text-muted-foreground">
                User: {sortedUsers.find((u: AdminUserBalance) => u.user_id === creditUserId)?.email}
              </p>
              <div>
                <label className="text-sm font-medium">Amount</label>
                <input
                  type="number"
                  value={creditAmount}
                  onChange={(e) => setCreditAmount(e.target.value)}
                  placeholder="e.g. 1000"
                  className="w-full mt-1 px-3 py-2 bg-background border rounded-md text-sm"
                />
              </div>
              <div>
                <label className="text-sm font-medium">Description</label>
                <input
                  type="text"
                  value={creditDescription}
                  onChange={(e) => setCreditDescription(e.target.value)}
                  placeholder="e.g. Monthly allocation"
                  className="w-full mt-1 px-3 py-2 bg-background border rounded-md text-sm"
                />
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={() => setCreditUserId(null)} className="px-4 py-2 text-sm border rounded-md">
                  Cancel
                </button>
                <button
                  onClick={() => {
                    const amt = parseFloat(creditAmount);
                    if (!amt || amt <= 0 || !creditDescription) {
                      toast.error('Please enter a valid amount and description');
                      return;
                    }
                    addCreditsMutation.mutate({ userId: creditUserId, amount: amt, description: creditDescription });
                  }}
                  disabled={addCreditsMutation.isPending}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
                >
                  {addCreditsMutation.isPending ? 'Adding...' : 'Add Sparks'}
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
      </>
      )}

      {/* Billing Logs Tab */}
      {activeTab === 'logs' && (
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Billing Logs</h2>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={logsUserSearchInput}
              onChange={(e) => setLogsUserSearchInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  setLogsUserSearch(logsUserSearchInput);
                  setLogsPage(0);
                }
              }}
              placeholder="Search user..."
              className="px-3 py-1.5 bg-background border rounded-md text-sm w-48"
            />
            <button
              onClick={() => { setLogsUserSearch(logsUserSearchInput); setLogsPage(0); }}
              className="p-1.5 text-muted-foreground hover:text-foreground rounded-md hover:bg-muted"
            >
              <Search className="h-4 w-4" />
            </button>
          </div>

          <select
            value={logsProvider}
            onChange={(e) => { setLogsProvider(e.target.value); setLogsPage(0); }}
            className="px-3 py-1.5 bg-background border rounded-md text-sm"
          >
            <option value="">All Providers</option>
            <option value="openai">openai</option>
            <option value="anthropic">anthropic</option>
            <option value="fal">fal</option>
          </select>

          <select
            value={logsOperation}
            onChange={(e) => { setLogsOperation(e.target.value); setLogsPage(0); }}
            className="px-3 py-1.5 bg-background border rounded-md text-sm"
          >
            <option value="">All Operations</option>
            <option value="tag">tag</option>
            <option value="describe">describe</option>
            <option value="embed">embed</option>
            <option value="generate">generate</option>
            <option value="train">train</option>
            <option value="expand_prompt">expand_prompt</option>
            <option value="summarize">summarize</option>
          </select>

          <div className="flex gap-1 bg-muted rounded-lg p-1">
            {(['7d', '30d', '90d', 'all'] as DateRange[]).map((range) => (
              <button
                key={range}
                onClick={() => { setLogsDateRange(range); setLogsPage(0); }}
                className={cn(
                  'px-3 py-1 text-sm rounded-md transition-colors',
                  logsDateRange === range ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'
                )}
              >
                {range === 'all' ? 'All' : range}
              </button>
            ))}
          </div>

          {(logsUserSearch || logsProvider || logsOperation) && (
            <button
              onClick={() => {
                setLogsUserSearch('');
                setLogsUserSearchInput('');
                setLogsProvider('');
                setLogsOperation('');
                setLogsPage(0);
              }}
              className="px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground border rounded-md"
            >
              Clear filters
            </button>
          )}
        </div>

        {/* Table */}
        {logsLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : (
          <>
          <div className="bg-card border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="w-8 px-2 py-3" />
                  <th className="text-left px-4 py-3 font-medium text-xs text-muted-foreground">Time</th>
                  <th className="text-left px-4 py-3 font-medium text-xs text-muted-foreground">User</th>
                  <th className="text-left px-4 py-3 font-medium text-xs text-muted-foreground">Operation</th>
                  <th className="text-left px-4 py-3 font-medium text-xs text-muted-foreground">Provider / Model</th>
                  <th className="text-right px-4 py-3 font-medium text-xs text-muted-foreground">Tokens</th>
                  <th className="text-right px-4 py-3 font-medium text-xs text-muted-foreground">Raw $</th>
                  <th className="text-right px-4 py-3 font-medium text-xs text-muted-foreground">Charged $</th>
                  <th className="text-right px-4 py-3 font-medium text-xs text-muted-foreground">Sparks</th>
                </tr>
              </thead>
              <tbody>
                {logsData?.items.map((entry: BillingLogEntry) => {
                  const isExpanded = expandedLogId === entry.id;
                  const hasDetail = entry.detail !== null;
                  const sparks = hasDetail ? (entry.detail!.sparks ?? 0) : (entry.charged_cost ?? 0) * 1000;
                  return (
                    <Fragment key={entry.id}>
                      <tr
                        className={cn(
                          'border-b cursor-pointer hover:bg-muted/30 transition-colors',
                          isExpanded && 'bg-muted/20',
                          !hasDetail && 'cursor-default'
                        )}
                        onClick={() => hasDetail && setExpandedLogId(isExpanded ? null : entry.id)}
                      >
                        <td className="w-8 px-2 py-2.5 text-muted-foreground">
                          {hasDetail && (
                            isExpanded
                              ? <ChevronDown className="h-4 w-4" />
                              : <ChevronRight className="h-4 w-4" />
                          )}
                        </td>
                        <td className="px-4 py-2.5 text-xs text-muted-foreground whitespace-nowrap">
                          {formatDateCompact(entry.created_at)}
                        </td>
                        <td className="px-4 py-2.5">
                          <span className="text-xs">{entry.user_email}</span>
                        </td>
                        <td className="px-4 py-2.5">
                          <span className="px-1.5 py-0.5 text-xs bg-muted rounded">{entry.operation}</span>
                        </td>
                        <td className="px-4 py-2.5 font-mono text-xs">
                          {entry.provider}/{entry.model.length > 30 ? entry.model.slice(0, 28) + '...' : entry.model}
                        </td>
                        <td className="text-right px-4 py-2.5 text-xs text-muted-foreground">
                          {entry.input_tokens || entry.output_tokens
                            ? `${entry.input_tokens ?? 0} / ${entry.output_tokens ?? 0}`
                            : '-'}
                        </td>
                        <td className="text-right px-4 py-2.5 font-mono text-xs">
                          ${(entry.raw_cost ?? 0).toFixed(6)}
                        </td>
                        <td className="text-right px-4 py-2.5 font-mono text-xs">
                          ${(entry.charged_cost ?? 0).toFixed(6)}
                        </td>
                        <td className="text-right px-4 py-2.5 font-mono text-xs font-medium">
                          {sparks.toFixed(2)}
                        </td>
                      </tr>
                      {isExpanded && hasDetail && (
                        <tr className="border-b bg-muted/10">
                          <td colSpan={9} className="px-10 py-3">
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                              <div>
                                <span className="text-muted-foreground">Rate/Input Token</span>
                                <p className="font-mono">{(entry.detail!.cost_per_input_token ?? 0).toFixed(10)}</p>
                              </div>
                              <div>
                                <span className="text-muted-foreground">Rate/Output Token</span>
                                <p className="font-mono">{(entry.detail!.cost_per_output_token ?? 0).toFixed(10)}</p>
                              </div>
                              <div>
                                <span className="text-muted-foreground">Rate/Call</span>
                                <p className="font-mono">${(entry.detail!.cost_per_call ?? 0).toFixed(6)}</p>
                              </div>
                              <div>
                                <span className="text-muted-foreground">Platform Markup</span>
                                <p className="font-mono">{entry.detail!.platform_markup}x</p>
                              </div>
                              <div>
                                <span className="text-muted-foreground">Input Cost</span>
                                <p className="font-mono">${(entry.detail!.input_cost ?? 0).toFixed(8)}</p>
                              </div>
                              <div>
                                <span className="text-muted-foreground">Output Cost</span>
                                <p className="font-mono">${(entry.detail!.output_cost ?? 0).toFixed(8)}</p>
                              </div>
                              <div>
                                <span className="text-muted-foreground">Call Cost</span>
                                <p className="font-mono">${(entry.detail!.call_cost ?? 0).toFixed(8)}</p>
                              </div>
                              {entry.pipeline_log_id && (
                                <div>
                                  <span className="text-muted-foreground">Pipeline Log ID</span>
                                  <p className="font-mono">{entry.pipeline_log_id}</p>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
                {(!logsData?.items.length) && (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                      No billing logs found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {logsData && logsData.total > 0 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                {logsData.total} records total
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setLogsPage(Math.max(0, logsPage - 1))}
                  disabled={logsPage === 0}
                  className="px-3 py-1.5 text-sm border rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted"
                >
                  Previous
                </button>
                <span className="text-sm text-muted-foreground">
                  Page {logsPage + 1} of {Math.ceil(logsData.total / LOGS_LIMIT)}
                </span>
                <button
                  onClick={() => setLogsPage(logsPage + 1)}
                  disabled={(logsPage + 1) * LOGS_LIMIT >= logsData.total}
                  className="px-3 py-1.5 text-sm border rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted"
                >
                  Next
                </button>
              </div>
            </div>
          )}
          </>
        )}
      </section>
      )}

      {/* Catalog Tab - Cost Catalog */}
      {activeTab === 'catalog' && (
      <section className="space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Cost Catalog</h2>
          <button
            onClick={() => {
              setEditingEntry(null);
              setCatalogForm({ provider: '', model: '', operation: '', cost_per_input_token: 0, cost_per_output_token: 0, cost_per_call: 0, platform_markup: 1.0, pricing_rules: '' });
              setShowCatalogForm(true);
            }}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" /> Add Entry
          </button>
        </div>

        {catalogLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : (
          <div className="space-y-6">
            {categoryOrder.map((cat) => {
              const group = catalogByCategory[cat];
              if (!group || (group.tokenModels.length === 0 && group.perCallEntries.length === 0)) return null;

              return (
                <div key={cat} className="space-y-3">
                  <p className="text-sm font-medium text-muted-foreground">{categoryLabels[cat]}</p>
                  <div className="bg-card border rounded-lg overflow-hidden">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b bg-muted/50">
                          <th className="w-8 px-2 py-2" />
                          <th className="text-left px-4 py-2 font-medium text-xs text-muted-foreground">Model</th>
                          <th className="text-right px-4 py-2 font-medium text-xs text-muted-foreground">Pricing</th>
                          <th className="text-right px-4 py-2 font-medium text-xs text-muted-foreground">Markup</th>
                          <th className="text-right px-4 py-2 font-medium text-xs text-muted-foreground">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {/* Token-based model rows (collapsible) */}
                        {group.tokenModels.map((mg) => {
                          const modelKey = `${mg.provider}::${mg.model}`;
                          const isExpanded = expandedTokenModels.has(modelKey);
                          const markups = mg.entries.map((e) => e.platform_markup);
                          const allSame = markups.every((m) => m === markups[0]);
                          const inputPrice = mg.entries[0].cost_per_input_token;
                          const outputPrice = mg.entries[0].cost_per_output_token;

                          return (
                            <Fragment key={modelKey}>
                              <tr
                                className={cn(
                                  'border-b cursor-pointer hover:bg-muted/30 transition-colors',
                                  isExpanded && 'bg-muted/20'
                                )}
                                onClick={() => {
                                  setExpandedTokenModels((prev) => {
                                    const next = new Set(prev);
                                    if (next.has(modelKey)) next.delete(modelKey);
                                    else next.add(modelKey);
                                    return next;
                                  });
                                }}
                              >
                                <td className="w-8 px-2 py-2.5 text-muted-foreground">
                                  {isExpanded
                                    ? <ChevronDown className="h-4 w-4" />
                                    : <ChevronRight className="h-4 w-4" />}
                                </td>
                                <td className="px-4 py-2.5">
                                  <span className="font-medium text-sm">{mg.model}</span>
                                  <span className="text-xs text-muted-foreground ml-2">{mg.provider}</span>
                                </td>
                                <td className="text-right px-4 py-2.5 text-xs text-muted-foreground whitespace-nowrap">
                                  {inputPrice ? `$${(inputPrice * 1_000_000).toFixed(2)}/1M in` : ''}
                                  {inputPrice && outputPrice ? ' · ' : ''}
                                  {outputPrice ? `$${(outputPrice * 1_000_000).toFixed(2)}/1M out` : ''}
                                </td>
                                <td className="text-right px-4 py-2.5 text-xs">
                                  {allSame
                                    ? `${markups[0]}x`
                                    : <span className="text-muted-foreground italic">varies</span>}
                                </td>
                                <td className="text-right px-4 py-2.5">
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setEditingModel({ provider: mg.provider, model: mg.model });
                                      setModelEditForm({
                                        cost_per_input_token: inputPrice || 0,
                                        cost_per_output_token: outputPrice || 0,
                                        cost_per_call: mg.entries[0].cost_per_call || 0,
                                        operations: mg.entries.map((en) => ({
                                          operation: en.operation,
                                          platform_markup: en.platform_markup,
                                        })),
                                      });
                                      setSetAllMarkup('');
                                    }}
                                    className="p-1 text-muted-foreground hover:text-foreground"
                                    title="Edit model pricing"
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                  </button>
                                </td>
                              </tr>
                              {isExpanded && mg.entries.map((e) => (
                                <tr key={e.id} className="border-b bg-muted/10">
                                  <td />
                                  <td className="px-4 py-1.5 pl-10">
                                    <span className="px-1.5 py-0.5 text-xs bg-muted rounded">{e.operation}</span>
                                  </td>
                                  <td />
                                  <td className="text-right px-4 py-1.5 text-xs">{e.platform_markup}x</td>
                                  <td />
                                </tr>
                              ))}
                            </Fragment>
                          );
                        })}

                        {/* Per-call entry rows */}
                        {group.perCallEntries.map((entry: CostCatalogEntry) => (
                          <tr key={entry.id} className="border-b last:border-0">
                            <td className="w-8 px-2 py-2.5" />
                            <td className="px-4 py-2.5">
                              <span className="font-mono text-xs">{entry.model}</span>
                              <span className="text-xs text-muted-foreground ml-2">{entry.provider}</span>
                            </td>
                            <td className="text-right px-4 py-2.5 font-mono text-xs">
                              ${entry.cost_per_call?.toFixed(4) ?? '0'}/call
                              {entry.pricing_rules && <span className="ml-1 text-[10px] text-amber-600 dark:text-amber-400" title={JSON.stringify(entry.pricing_rules)}>VAR</span>}
                            </td>
                            <td className="text-right px-4 py-2.5 text-xs">{entry.platform_markup}x</td>
                            <td className="text-right px-4 py-2.5">
                              <div className="flex items-center justify-end gap-1">
                                <button
                                  onClick={() => {
                                    setEditingEntry(entry);
                                    setCatalogForm({
                                      provider: entry.provider,
                                      model: entry.model,
                                      operation: entry.operation,
                                      cost_per_input_token: entry.cost_per_input_token || 0,
                                      cost_per_output_token: entry.cost_per_output_token || 0,
                                      cost_per_call: entry.cost_per_call || 0,
                                      platform_markup: entry.platform_markup,
                                      pricing_rules: entry.pricing_rules ? JSON.stringify(entry.pricing_rules, null, 2) : '',
                                    });
                                    setShowCatalogForm(true);
                                  }}
                                  className="p-1 text-muted-foreground hover:text-foreground"
                                >
                                  <Pencil className="h-3.5 w-3.5" />
                                </button>
                                <button
                                  onClick={() => {
                                    if (confirm('Delete this catalog entry?')) {
                                      deleteCatalogMutation.mutate(entry.id);
                                    }
                                  }}
                                  className="p-1 text-muted-foreground hover:text-red-500"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Single entry form dialog (for per-call entries and new entries) */}
        {showCatalogForm && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCatalogForm(false)}>
            <div className="bg-card border rounded-lg p-6 w-[480px] space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-semibold">{editingEntry ? 'Edit Catalog Entry' : 'New Catalog Entry'}</h3>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs font-medium">Provider</label>
                  <input
                    type="text"
                    value={catalogForm.provider}
                    onChange={(e) => setCatalogForm({ ...catalogForm, provider: e.target.value })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Model</label>
                  <input
                    type="text"
                    value={catalogForm.model}
                    onChange={(e) => setCatalogForm({ ...catalogForm, model: e.target.value })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Operation</label>
                  <input
                    type="text"
                    value={catalogForm.operation}
                    onChange={(e) => setCatalogForm({ ...catalogForm, operation: e.target.value })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium">Cost/Input Token</label>
                  <input
                    type="number"
                    step="any"
                    value={catalogForm.cost_per_input_token}
                    onChange={(e) => setCatalogForm({ ...catalogForm, cost_per_input_token: parseFloat(e.target.value) || 0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Cost/Output Token</label>
                  <input
                    type="number"
                    step="any"
                    value={catalogForm.cost_per_output_token}
                    onChange={(e) => setCatalogForm({ ...catalogForm, cost_per_output_token: parseFloat(e.target.value) || 0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Cost/Call</label>
                  <input
                    type="number"
                    step="any"
                    value={catalogForm.cost_per_call}
                    onChange={(e) => setCatalogForm({ ...catalogForm, cost_per_call: parseFloat(e.target.value) || 0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Markup Multiplier</label>
                  <input
                    type="number"
                    step="0.01"
                    value={catalogForm.platform_markup}
                    onChange={(e) => setCatalogForm({ ...catalogForm, platform_markup: parseFloat(e.target.value) || 1.0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-medium">Pricing Rules (JSON, optional)</label>
                <textarea
                  value={catalogForm.pricing_rules}
                  onChange={(e) => setCatalogForm({ ...catalogForm, pricing_rules: e.target.value })}
                  placeholder='{"pricing_type":"flat_with_modifiers","base_cost":0.15,...}'
                  rows={4}
                  className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm font-mono"
                />
                {catalogForm.pricing_rules && (() => { try { JSON.parse(catalogForm.pricing_rules); return null; } catch { return <p className="text-xs text-red-500 mt-1">Invalid JSON</p>; } })()}
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={() => setShowCatalogForm(false)} className="px-4 py-2 text-sm border rounded-md">
                  Cancel
                </button>
                <button
                  onClick={() => {
                    if (!catalogForm.provider || !catalogForm.model || !catalogForm.operation) {
                      toast.error('Provider, model, and operation are required');
                      return;
                    }
                    saveCatalogMutation.mutate({
                      ...(editingEntry ? { id: editingEntry.id } : {}),
                      ...catalogForm,
                    });
                  }}
                  disabled={saveCatalogMutation.isPending}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
                >
                  {saveCatalogMutation.isPending ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Model edit dialog (for token-based models) */}
        {editingModel && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setEditingModel(null)}>
            <div className="bg-card border rounded-lg p-6 w-[520px] space-y-4 max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-semibold">
                Edit {editingModel.model}
                <span className="text-sm font-normal text-muted-foreground ml-2">{editingModel.provider}</span>
              </h3>

              {/* Base pricing */}
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs font-medium">Cost/Input Token</label>
                  <input
                    type="number"
                    step="any"
                    value={modelEditForm.cost_per_input_token}
                    onChange={(e) => setModelEditForm({ ...modelEditForm, cost_per_input_token: parseFloat(e.target.value) || 0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm font-mono"
                  />
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    ${(modelEditForm.cost_per_input_token * 1_000_000).toFixed(2)}/1M
                  </p>
                </div>
                <div>
                  <label className="text-xs font-medium">Cost/Output Token</label>
                  <input
                    type="number"
                    step="any"
                    value={modelEditForm.cost_per_output_token}
                    onChange={(e) => setModelEditForm({ ...modelEditForm, cost_per_output_token: parseFloat(e.target.value) || 0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm font-mono"
                  />
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    ${(modelEditForm.cost_per_output_token * 1_000_000).toFixed(2)}/1M
                  </p>
                </div>
                <div>
                  <label className="text-xs font-medium">Cost/Call</label>
                  <input
                    type="number"
                    step="any"
                    value={modelEditForm.cost_per_call}
                    onChange={(e) => setModelEditForm({ ...modelEditForm, cost_per_call: parseFloat(e.target.value) || 0 })}
                    className="w-full mt-1 px-2 py-1.5 bg-background border rounded-md text-sm font-mono"
                  />
                </div>
              </div>

              {/* Set All Markups */}
              <div className="flex items-center gap-2 pt-1">
                <label className="text-xs font-medium whitespace-nowrap">Set All Markups</label>
                <input
                  type="number"
                  step="0.1"
                  value={setAllMarkup}
                  onChange={(e) => setSetAllMarkup(e.target.value)}
                  placeholder="e.g. 2.0"
                  className="w-24 px-2 py-1 bg-background border rounded-md text-sm"
                />
                <button
                  onClick={() => {
                    const v = parseFloat(setAllMarkup);
                    if (!v || v <= 0) { toast.error('Enter a valid markup'); return; }
                    setModelEditForm({
                      ...modelEditForm,
                      operations: modelEditForm.operations.map((op) => ({ ...op, platform_markup: v })),
                    });
                    setSetAllMarkup('');
                  }}
                  className="px-2 py-1 text-xs bg-muted rounded-md hover:bg-muted/80"
                >
                  Apply
                </button>
              </div>

              {/* Operations list */}
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Per-Operation Markup</p>
                <div className="grid grid-cols-2 gap-2">
                  {modelEditForm.operations.map((op, idx) => (
                    <div key={op.operation} className="flex items-center gap-2 bg-muted/30 rounded-md px-2 py-1.5">
                      <span className="text-xs flex-1 truncate">{op.operation}</span>
                      <input
                        type="number"
                        step="0.1"
                        value={op.platform_markup}
                        onChange={(e) => {
                          const ops = [...modelEditForm.operations];
                          ops[idx] = { ...ops[idx], platform_markup: parseFloat(e.target.value) || 1.0 };
                          setModelEditForm({ ...modelEditForm, operations: ops });
                        }}
                        className="w-16 px-1.5 py-0.5 bg-background border rounded text-xs text-right"
                      />
                      <span className="text-xs text-muted-foreground">x</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex gap-2 justify-end pt-2">
                <button onClick={() => setEditingModel(null)} className="px-4 py-2 text-sm border rounded-md">
                  Cancel
                </button>
                <button
                  onClick={() => {
                    bulkUpdateMutation.mutate({
                      provider: editingModel.provider,
                      model: editingModel.model,
                      cost_per_input_token: modelEditForm.cost_per_input_token,
                      cost_per_output_token: modelEditForm.cost_per_output_token,
                      cost_per_call: modelEditForm.cost_per_call,
                      operations: modelEditForm.operations,
                    });
                  }}
                  disabled={bulkUpdateMutation.isPending}
                  className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
                >
                  {bulkUpdateMutation.isPending ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
      )}

      {activeTab === 'operations' && (
        <OperationsMonitor />
      )}
    </div>
  );
}
