'use client';

import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import { Loader2, Zap, TrendingDown, ArrowUpRight, ArrowDownRight, Sparkles, ShoppingBag, Crown, Gift, XCircle, ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import { billingApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { cn, formatDateCompact, formatNumber } from '@/lib/utils';
import type { BalanceTransaction, Purchase, SparkPack, SubscriptionPlan } from '@/types';

type DateRange = '7d' | '30d' | '90d' | 'all';

function getStartDate(range: DateRange): string | undefined {
  if (range === 'all') return undefined;
  const days = range === '7d' ? 7 : range === '30d' ? 30 : 90;
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

function formatPrice(cents: number, currency: string = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
  }).format(cents / 100);
}

function PackCard({ pack, onBuy, loading }: { pack: SparkPack; onBuy: (id: number) => void; loading: boolean }) {
  const totalSparks = pack.sparks_amount + pack.bonus_sparks;
  return (
    <div className={cn(
      'relative bg-card border rounded-lg p-5 flex flex-col items-center text-center transition-shadow hover:shadow-md',
      pack.is_featured && 'border-amber-400 ring-1 ring-amber-400/50'
    )}>
      {pack.is_featured && (
        <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 bg-amber-400 text-amber-950 text-xs font-semibold px-3 py-0.5 rounded-full">
          Popular
        </span>
      )}
      <h3 className="text-lg font-semibold mt-1">{pack.name}</h3>
      <p className="text-3xl font-bold mt-2">{formatPrice(pack.price_cents, pack.currency)}</p>
      <div className="mt-3 space-y-1">
        <p className="text-sm">
          <span className="font-medium">{pack.sparks_amount.toLocaleString()}</span> sparks
        </p>
        {pack.bonus_sparks > 0 && (
          <p className="text-sm text-amber-600 dark:text-amber-400 font-medium">
            +{pack.bonus_sparks.toLocaleString()} bonus
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {totalSparks.toLocaleString()} total
        </p>
      </div>
      <button
        onClick={() => onBuy(pack.id)}
        disabled={loading}
        className={cn(
          'mt-4 w-full py-2 px-4 rounded-md text-sm font-medium transition-colors',
          pack.is_featured
            ? 'bg-amber-400 text-amber-950 hover:bg-amber-500'
            : 'bg-primary text-primary-foreground hover:bg-primary/90',
          'disabled:opacity-50'
        )}
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin mx-auto" /> : 'Buy'}
      </button>
    </div>
  );
}

function PlanCard({ plan, onSubscribe, loading }: { plan: SubscriptionPlan; onSubscribe: (id: number) => void; loading: boolean }) {
  const isPro = plan.name === 'Pro';
  return (
    <div className={cn(
      'relative bg-card border rounded-lg p-5 flex flex-col items-center text-center transition-shadow hover:shadow-md',
      isPro && 'border-violet-400 ring-1 ring-violet-400/50'
    )}>
      {isPro && (
        <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 bg-violet-500 text-white text-xs font-semibold px-3 py-0.5 rounded-full">
          Best Value
        </span>
      )}
      <h3 className="text-lg font-semibold mt-1">{plan.name}</h3>
      <p className="text-3xl font-bold mt-2">{formatPrice(plan.price_cents, plan.currency)}<span className="text-sm font-normal text-muted-foreground">/mo</span></p>
      <div className="mt-3">
        <p className="text-sm">
          <span className="font-medium">{plan.sparks_per_month.toLocaleString()}</span> sparks/month
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          {formatPrice(Math.round(plan.price_cents / (plan.sparks_per_month / 1000)), plan.currency)} per 1k sparks
        </p>
      </div>
      <button
        onClick={() => onSubscribe(plan.id)}
        disabled={loading}
        className={cn(
          'mt-4 w-full py-2 px-4 rounded-md text-sm font-medium transition-colors',
          isPro
            ? 'bg-violet-500 text-white hover:bg-violet-600'
            : 'bg-primary text-primary-foreground hover:bg-primary/90',
          'disabled:opacity-50'
        )}
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin mx-auto" /> : 'Subscribe'}
      </button>
    </div>
  );
}

export default function BillingPage() {
  const [dateRange, setDateRange] = useState<DateRange>('30d');
  const [txnPage, setTxnPage] = useState(0);
  const [buyingPackId, setBuyingPackId] = useState<number | null>(null);
  const [subscribingPlanId, setSubscribingPlanId] = useState<number | null>(null);
  const [cancellingSubscription, setCancellingSubscription] = useState(false);
  const [promoCode, setPromoCode] = useState('');
  const [redeemingPromo, setRedeemingPromo] = useState(false);
  const [manualPack, setManualPack] = useState<SparkPack | null>(null);
  const [manualReference, setManualReference] = useState('');
  const [submittingClaim, setSubmittingClaim] = useState(false);
  const { user } = useAuth();
  const txnLimit = 25;
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const purchasePolled = useRef(false);
  const subscriptionPolled = useRef(false);

  const startDate = getStartDate(dateRange);

  // Handle ?purchase=success redirect
  useEffect(() => {
    if (searchParams.get('purchase') === 'success' && !purchasePolled.current) {
      purchasePolled.current = true;
      toast.success('Payment received! Your sparks are being added...');
      let polls = 0;
      const interval = setInterval(() => {
        queryClient.invalidateQueries({ queryKey: ['billing', 'balance'] });
        queryClient.invalidateQueries({ queryKey: ['billing', 'transactions'] });
        polls++;
        if (polls >= 15) clearInterval(interval);
      }, 2000);
      return () => clearInterval(interval);
    }
  }, [searchParams, queryClient]);

  // Handle ?subscription=success redirect
  useEffect(() => {
    if (searchParams.get('subscription') === 'success' && !subscriptionPolled.current) {
      subscriptionPolled.current = true;
      toast.success('Subscription activated! Your sparks are being added...');
      let polls = 0;
      const interval = setInterval(() => {
        queryClient.invalidateQueries({ queryKey: ['billing', 'balance'] });
        queryClient.invalidateQueries({ queryKey: ['billing', 'subscription'] });
        queryClient.invalidateQueries({ queryKey: ['billing', 'transactions'] });
        polls++;
        if (polls >= 15) clearInterval(interval);
      }, 2000);
      return () => clearInterval(interval);
    }
  }, [searchParams, queryClient]);

  const { data: balance, isLoading: balanceLoading } = useQuery({
    queryKey: ['billing', 'balance'],
    queryFn: billingApi.getBalance,
    refetchInterval: 30000,
  });

  const { data: packs, isLoading: packsLoading } = useQuery({
    queryKey: ['billing', 'packs'],
    queryFn: billingApi.getPacks,
  });

  const { data: paymentConfig } = useQuery({
    queryKey: ['billing', 'payment-config'],
    queryFn: billingApi.getPaymentConfig,
    staleTime: 5 * 60 * 1000,
  });

  const { data: subPlans, isLoading: subPlansLoading } = useQuery({
    queryKey: ['billing', 'subscription-plans'],
    queryFn: billingApi.getSubscriptionPlans,
  });

  const { data: subscription, isLoading: subLoading } = useQuery({
    queryKey: ['billing', 'subscription'],
    queryFn: billingApi.getSubscription,
  });

  const { data: usage, isLoading: usageLoading } = useQuery({
    queryKey: ['billing', 'usage', dateRange],
    queryFn: () => billingApi.getUsage(startDate),
  });

  const { data: transactions, isLoading: txnLoading } = useQuery({
    queryKey: ['billing', 'transactions', txnPage],
    queryFn: () => billingApi.getTransactions(txnPage * txnLimit, txnLimit),
  });

  const { data: purchases, isLoading: purchasesLoading } = useQuery({
    queryKey: ['billing', 'purchases'],
    queryFn: () => billingApi.getPurchases(),
  });

  const handleBuy = async (packId: number) => {
    // Without an automated gateway, purchases go through the manual PayPal flow
    if (paymentConfig && !paymentConfig.automated) {
      if (paymentConfig.manual_enabled) {
        const pack = packs?.find((p) => p.id === packId) || null;
        setManualReference('');
        setManualPack(pack);
      } else {
        toast.error('Purchases are not available yet. Please check back soon.');
      }
      return;
    }

    setBuyingPackId(packId);
    try {
      const currentUrl = window.location.origin + '/billing';
      const result = await billingApi.createCheckout(
        packId,
        `${currentUrl}?purchase=success`,
        currentUrl,
      );
      window.location.href = result.checkout_url;
    } catch {
      toast.error('Failed to start checkout. Please try again.');
      setBuyingPackId(null);
    }
  };

  const handleSubmitClaim = async () => {
    if (!manualPack || !manualReference.trim()) return;
    setSubmittingClaim(true);
    try {
      await billingApi.submitManualClaim(manualPack.id, manualReference.trim());
      toast.success('Payment claim submitted! Sparks will be credited after review (usually within 24h).');
      setManualPack(null);
      queryClient.invalidateQueries({ queryKey: ['billing', 'purchases'] });
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to submit claim.';
      toast.error(msg);
    } finally {
      setSubmittingClaim(false);
    }
  };

  const handleSubscribe = async (planId: number) => {
    setSubscribingPlanId(planId);
    try {
      const currentUrl = window.location.origin + '/billing';
      const result = await billingApi.createSubscriptionCheckout(
        planId,
        `${currentUrl}?subscription=success`,
        currentUrl,
      );
      window.location.href = result.checkout_url;
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to start checkout.';
      toast.error(msg);
      setSubscribingPlanId(null);
    }
  };

  const handleCancelSubscription = async () => {
    if (!confirm('Are you sure you want to cancel your subscription? You will keep access until the end of your billing period.')) return;
    setCancellingSubscription(true);
    try {
      await billingApi.cancelSubscription();
      toast.success('Subscription cancelled. Access continues until period end.');
      queryClient.invalidateQueries({ queryKey: ['billing', 'subscription'] });
    } catch {
      toast.error('Failed to cancel subscription.');
    } finally {
      setCancellingSubscription(false);
    }
  };

  const handleRedeemPromo = async () => {
    if (!promoCode.trim()) return;
    setRedeemingPromo(true);
    try {
      const result = await billingApi.redeemPromo(promoCode.trim());
      toast.success(`Redeemed! ${result.sparks_granted.toLocaleString()} sparks added.`);
      setPromoCode('');
      queryClient.invalidateQueries({ queryKey: ['billing', 'balance'] });
      queryClient.invalidateQueries({ queryKey: ['billing', 'transactions'] });
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Invalid promo code.';
      toast.error(msg);
    } finally {
      setRedeemingPromo(false);
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case 'active': return 'bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-300';
      case 'cancelled': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/50 dark:text-yellow-300';
      case 'past_due': return 'bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300';
      default: return 'bg-gray-100 text-gray-800 dark:bg-gray-900/50 dark:text-gray-300';
    }
  };

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
          </>
        ) : null}
      </div>

      {/* Active Subscription Banner */}
      {!subLoading && subscription && (
        <div className="bg-card border border-violet-300 dark:border-violet-700 rounded-lg p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Crown className="h-6 w-6 text-violet-500" />
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold">{subscription.plan_name} Plan</h3>
                  <span className={cn('px-2 py-0.5 rounded-full text-xs font-medium', statusColor(subscription.status))}>
                    {subscription.status}
                  </span>
                </div>
                <p className="text-sm text-muted-foreground">
                  {subscription.sparks_per_month.toLocaleString()} sparks/month
                  {subscription.current_period_end && (
                    <> &middot; Renews {formatDateCompact(subscription.current_period_end)}</>
                  )}
                </p>
                {subscription.cancel_at_period_end && (
                  <p className="text-xs text-yellow-600 dark:text-yellow-400 mt-1">
                    Cancels at period end
                  </p>
                )}
              </div>
            </div>
            {subscription.status === 'active' && !subscription.cancel_at_period_end && (
              <button
                onClick={handleCancelSubscription}
                disabled={cancellingSubscription}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-red-600 hover:text-red-700 border border-red-200 dark:border-red-800 rounded-md hover:bg-red-50 dark:hover:bg-red-950 transition-colors disabled:opacity-50"
              >
                {cancellingSubscription ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
                Cancel
              </button>
            )}
          </div>
        </div>
      )}

      {/* Subscription Plans (show if no active subscription) */}
      {!subLoading && (!subscription || subscription.status === 'expired' || subscription.status === 'cancelled') && (
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Crown className="h-5 w-5 text-violet-500" />
            <h2 className="text-lg font-semibold">Subscription Plans</h2>
          </div>
          {subPlansLoading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
          ) : subPlans && subPlans.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {subPlans.map((plan) => (
                <PlanCard
                  key={plan.id}
                  plan={plan}
                  onSubscribe={handleSubscribe}
                  loading={subscribingPlanId === plan.id}
                />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No subscription plans available.</p>
          )}
        </section>
      )}

      {/* Redeem Promo Code */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Gift className="h-5 w-5 text-emerald-500" />
          <h2 className="text-lg font-semibold">Promo Code</h2>
        </div>
        <div className="flex gap-3 max-w-md">
          <input
            type="text"
            value={promoCode}
            onChange={(e) => setPromoCode(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && handleRedeemPromo()}
            placeholder="Enter promo code"
            className="flex-1 px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button
            onClick={handleRedeemPromo}
            disabled={redeemingPromo || !promoCode.trim()}
            className="px-4 py-2 text-sm font-medium bg-emerald-500 text-white rounded-md hover:bg-emerald-600 disabled:opacity-50 transition-colors"
          >
            {redeemingPromo ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Redeem'}
          </button>
        </div>
      </section>

      {/* Buy Sparks */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="h-5 w-5 text-amber-400" />
          <h2 className="text-lg font-semibold">Buy Sparks</h2>
        </div>
        {packsLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : packs && packs.length > 0 ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {packs.map((pack) => (
              <PackCard
                key={pack.id}
                pack={pack}
                onBuy={handleBuy}
                loading={buyingPackId === pack.id}
              />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No spark packs available.</p>
        )}
      </section>

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

            {/* By operation — detailed table */}
            {usage.by_operation_detail && usage.by_operation_detail.length > 0 && (
              <div className="bg-card border rounded-lg overflow-hidden">
                <div className="px-4 py-3 border-b">
                  <p className="text-sm font-medium">By Operation</p>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/50">
                      <th className="text-left px-4 py-2 font-medium">Operation</th>
                      <th className="text-right px-4 py-2 font-medium">Count</th>
                      <th className="text-right px-4 py-2 font-medium">Total Sparks</th>
                      <th className="text-right px-4 py-2 font-medium">Avg/Call</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.by_operation_detail.map((row) => (
                      <tr key={row.operation} className="border-b last:border-0">
                        <td className="px-4 py-2">{row.operation}</td>
                        <td className="px-4 py-2 text-right font-mono">{row.count.toLocaleString()}</td>
                        <td className="px-4 py-2 text-right font-mono">{formatNumber(row.total_sparks)}</td>
                        <td className="px-4 py-2 text-right font-mono text-muted-foreground">{row.avg_sparks.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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

      {/* Purchase History */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <ShoppingBag className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-lg font-semibold">Purchases</h2>
        </div>
        {purchasesLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : purchases && purchases.items.length > 0 ? (
          <div className="bg-card border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left px-4 py-3 font-medium">Date</th>
                  <th className="text-left px-4 py-3 font-medium">Pack</th>
                  <th className="text-right px-4 py-3 font-medium">Sparks</th>
                  <th className="text-right px-4 py-3 font-medium">Amount</th>
                  <th className="text-center px-4 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {purchases.items.map((p: Purchase) => (
                  <tr key={p.id} className="border-b last:border-0">
                    <td className="px-4 py-3 text-muted-foreground">{formatDateCompact(p.created_at)}</td>
                    <td className="px-4 py-3 font-medium">{p.pack_name}</td>
                    <td className="px-4 py-3 text-right font-mono">{p.sparks_amount.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatPrice(p.amount_cents, p.currency)}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={cn(
                        'inline-flex px-2 py-0.5 rounded-full text-xs font-medium',
                        p.status === 'completed'
                          ? 'bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-300'
                          : p.status === 'pending'
                          ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/50 dark:text-yellow-300'
                          : p.status === 'refunded'
                          ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-300'
                          : 'bg-gray-100 text-gray-800 dark:bg-gray-900/50 dark:text-gray-300'
                      )}>
                        {p.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-8 text-muted-foreground">No purchases yet</div>
        )}
      </section>

      {/* Manual PayPal payment dialog */}
      {manualPack && paymentConfig?.paypal_me_url && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-card border border-border rounded-lg w-full max-w-md p-6 space-y-4">
            <div>
              <h3 className="text-lg font-semibold">Pay with PayPal</h3>
              <p className="text-sm text-muted-foreground mt-1">
                {manualPack.name} pack — {formatPrice(manualPack.price_cents, manualPack.currency)} for{' '}
                {(manualPack.sparks_amount + manualPack.bonus_sparks).toLocaleString()} sparks
              </p>
            </div>

            <ol className="space-y-3 text-sm list-decimal pl-5">
              <li>
                Send{' '}
                <span className="font-semibold">{formatPrice(manualPack.price_cents, manualPack.currency)}</span>{' '}
                via PayPal:{' '}
                <a
                  href={`${paymentConfig.paypal_me_url.replace(/\/+$/, '')}/${(manualPack.price_cents / 100).toFixed(2)}USD`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-primary underline font-medium"
                >
                  Open PayPal <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </li>
              <li>
                Include your account email{user?.email ? (
                  <> (<span className="font-medium">{user.email}</span>)</>
                ) : null}{' '}
                in the payment note.
              </li>
              <li>Paste the PayPal transaction ID below.</li>
            </ol>

            <div>
              <label htmlFor="paypal-ref" className="block text-sm font-medium mb-1">
                PayPal transaction ID
              </label>
              <input
                id="paypal-ref"
                type="text"
                value={manualReference}
                onChange={(e) => setManualReference(e.target.value)}
                placeholder="e.g. 1AB23456CD789012E"
                className="w-full px-3 py-2 bg-background border border-input rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <p className="mt-1.5 text-xs text-muted-foreground">
                Sparks are credited after a quick manual review — usually within 24 hours.
              </p>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setManualPack(null)}
                disabled={submittingClaim}
                className="py-2 px-4 rounded-md text-sm font-medium border border-border hover:bg-secondary transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmitClaim}
                disabled={submittingClaim || manualReference.trim().length < 8}
                className="py-2 px-4 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {submittingClaim ? <Loader2 className="h-4 w-4 animate-spin mx-auto" /> : 'I paid — submit'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
