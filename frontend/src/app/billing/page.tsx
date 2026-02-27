'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2, Zap, TrendingDown, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { billingApi } from '@/lib/api';
import { cn, formatDateCompact, formatNumber } from '@/lib/utils';
import type { BalanceTransaction } from '@/types';

type DateRange = '7d' | '30d' | '90d' | 'all';

function getStartDate(range: DateRange): string | undefined {
  if (range === 'all') return undefined;
  const days = range === '7d' ? 7 : range === '30d' ? 30 : 90;
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

export default function BillingPage() {
  const [dateRange, setDateRange] = useState<DateRange>('30d');
  const [txnPage, setTxnPage] = useState(0);
  const txnLimit = 25;

  const startDate = getStartDate(dateRange);

  const { data: balance, isLoading: balanceLoading } = useQuery({
    queryKey: ['billing', 'balance'],
    queryFn: billingApi.getBalance,
    refetchInterval: 30000,
  });

  const { data: usage, isLoading: usageLoading } = useQuery({
    queryKey: ['billing', 'usage', dateRange],
    queryFn: () => billingApi.getUsage(startDate),
  });

  const { data: transactions, isLoading: txnLoading } = useQuery({
    queryKey: ['billing', 'transactions', txnPage],
    queryFn: () => billingApi.getTransactions(txnPage * txnLimit, txnLimit),
  });

  return (
    <div className="p-6 space-y-8 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold">Billing</h1>

      {/* Balance Card */}
      <div className="bg-card border rounded-lg p-8 text-center">
        {balanceLoading ? (
          <Loader2 className="h-6 w-6 animate-spin mx-auto" />
        ) : balance ? (
          <>
            <Zap className="h-10 w-10 mx-auto text-amber-400 mb-2" />
            <p className="text-sm text-muted-foreground mb-1">Available Sparks</p>
            <p className={cn(
              'text-5xl font-bold',
              (balance.available ?? balance.balance) < 10 ? 'text-red-500' : 'text-foreground'
            )}>
              {formatNumber(balance.available ?? balance.balance)}
            </p>
            {(balance.reserved ?? 0) > 0 && (
              <p className="text-xs text-muted-foreground mt-1">
                {formatNumber(balance.reserved)} reserved for in-progress operations
              </p>
            )}
            <p className="text-xs text-muted-foreground mt-2">1 spark = $0.001 USD</p>
          </>
        ) : null}
      </div>

      {/* Usage Summary */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Usage Summary</h2>
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

        {usageLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : usage ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-card border rounded-lg p-4">
                <div className="flex items-center gap-2">
                  <TrendingDown className="h-4 w-4 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">Total Spent</p>
                </div>
                <p className="text-2xl font-bold mt-1">{formatNumber(usage.total_cost)} sparks</p>
              </div>
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm text-muted-foreground">API Calls</p>
                <p className="text-2xl font-bold mt-1">{usage.record_count.toLocaleString()}</p>
              </div>
            </div>

            {/* By provider */}
            {Object.keys(usage.by_provider).length > 0 && (
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm font-medium mb-3">By Provider</p>
                <div className="space-y-2">
                  {Object.entries(usage.by_provider)
                    .sort(([, a], [, b]) => b - a)
                    .map(([provider, cost]) => (
                      <div key={provider} className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground capitalize">{provider}</span>
                        <span className="font-medium">{formatNumber(cost, 4)} credits</span>
                      </div>
                    ))}
                </div>
              </div>
            )}

            {/* By operation */}
            {Object.keys(usage.by_operation).length > 0 && (
              <div className="bg-card border rounded-lg p-4">
                <p className="text-sm font-medium mb-3">By Operation</p>
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(usage.by_operation)
                    .sort(([, a], [, b]) => b - a)
                    .map(([op, cost]) => (
                      <div key={op} className="flex items-center justify-between text-sm bg-muted rounded-lg px-3 py-2">
                        <span className="text-muted-foreground">{op}</span>
                        <span className="font-medium">{formatNumber(cost, 4)}</span>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </div>
        ) : null}
      </section>

      {/* Transaction History */}
      <section>
        <h2 className="text-lg font-semibold mb-4">Transaction History</h2>
        {txnLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : transactions && transactions.items.length > 0 ? (
          <>
            <div className="bg-card border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="text-left px-4 py-3 font-medium">Date</th>
                    <th className="text-left px-4 py-3 font-medium">Type</th>
                    <th className="text-left px-4 py-3 font-medium">Description</th>
                    <th className="text-right px-4 py-3 font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.items.map((txn: BalanceTransaction) => (
                    <tr key={txn.id} className="border-b last:border-0">
                      <td className="px-4 py-3 text-muted-foreground">{formatDateCompact(txn.created_at)}</td>
                      <td className="px-4 py-3">
                        <span className={cn(
                          'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
                          txn.transaction_type === 'credit'
                            ? 'bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-300'
                            : txn.transaction_type === 'debit'
                            ? 'bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300'
                            : 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-300'
                        )}>
                          {txn.transaction_type === 'credit' ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                          {txn.transaction_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground truncate max-w-[300px]">{txn.description}</td>
                      <td className={cn(
                        'text-right px-4 py-3 font-medium',
                        txn.amount > 0 ? 'text-green-600' : 'text-red-600'
                      )}>
                        {txn.amount > 0 ? '+' : ''}{formatNumber(txn.amount, 4)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Pagination */}
            {transactions.total > txnLimit && (
              <div className="flex items-center justify-between mt-4">
                <p className="text-sm text-muted-foreground">
                  Showing {txnPage * txnLimit + 1}-{Math.min((txnPage + 1) * txnLimit, transactions.total)} of {transactions.total}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setTxnPage(Math.max(0, txnPage - 1))}
                    disabled={txnPage === 0}
                    className="px-3 py-1 text-sm border rounded-md disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setTxnPage(txnPage + 1)}
                    disabled={(txnPage + 1) * txnLimit >= transactions.total}
                    className="px-3 py-1 text-sm border rounded-md disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="text-center py-8 text-muted-foreground">No transactions yet</div>
        )}
      </section>
    </div>
  );
}
