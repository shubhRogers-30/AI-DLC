import { CommonModule } from '@angular/common';
import { HttpClient, HttpErrorResponse, HttpHeaders, HttpParams } from '@angular/common/http';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit, OnDestroy {
  readonly stages = [
    { id: 'branch', label: 'Create or reuse branch', group: 'Prepare' },
    { id: 'load_story', label: 'Jira requirements', group: 'Intake' },
    { id: 'architecture', label: 'Architecture', group: 'Plan' },
    { id: 'human_approval', label: 'Architecture approval', group: 'Plan' },
    { id: 'plan', label: 'Task planning', group: 'Build' },
    { id: 'develop', label: 'Implementation', group: 'Build' },
    { id: 'tests', label: 'Build and tests', group: 'Verify' },
    { id: 'code_approval', label: 'Pre-push review', group: 'Review' },
    { id: 'create_pr', label: 'Branch and pull request', group: 'Publish' },
    { id: 'quality', label: 'CodeQL and SonarQube', group: 'Verify' },
    { id: 'final_approval', label: 'Final PR approval', group: 'Review' }
  ];
  apiUrl = sessionStorage.getItem('ai-dlc-api-url') || window.location.origin;
  apiToken = sessionStorage.getItem('ai-dlc-api-token') || '';
  connected = false;
  connecting = false;
  connectionError = '';
  tickets: any[] = [];
  repositories: any[] = [];
  selectedTicket: any = null;
  selectedRepository = '';
  targets: any[] = [];
  selectedTarget = '';
  targetError = '';
  targetNeedsOptIn = false;
  checkingTarget = false;
  repositoryDefaultBranch = '';
  branches: any[] = [];
  branchName = '';
  baseBranch = '';
  branchConflict: any = null;
  checkingBranch = false;
  reuseExistingBranch = false;
  branchError = '';
  ticketFilter = '';
  ticketLoading = false;
  startLoading = false;
  requestError = '';
  run: any = null;
  events: any[] = [];
  diff: any = { files: [], diff: '', updated_at: '' };
  selectedDiffFile = '';
  approvalComment = '';
  approver = sessionStorage.getItem('ai-dlc-approver') || '';
  approvalLoading = false;
  lastUpdated = '';
  private pollHandle: number | null = null;
  private polling = false;

  constructor(private readonly http: HttpClient) {}

  ngOnInit(): void {
    const issue = new URLSearchParams(window.location.search).get('issue');
    if (this.apiToken) void this.connect(issue || undefined);
  }

  ngOnDestroy(): void { this.stopPolling(); }

  get filteredTickets(): any[] {
    const query = this.ticketFilter.trim().toLowerCase();
    return query ? this.tickets.filter(ticket => `${ticket.key} ${ticket.summary} ${ticket.description}`.toLowerCase().includes(query)) : this.tickets;
  }

  get repositoryOptions(): string[] {
    const candidates = this.selectedTicket?.repository_candidates || [];
    return candidates.length ? candidates : this.repositories.map(repository => repository.full_name);
  }

  get selectedProfile(): string { return this.targets.find(target => target.name === this.selectedTarget)?.stack || ''; }

  get currentApprovalLabel(): string {
    return ({ architecture_approval: 'Approve architecture', code_approval: 'Approve code for push', merge_approval: 'Approve PR for manual merge' } as Record<string, string>)[this.run?.pending_approval?.type || ''] || 'Review workflow';
  }

  get currentFileDiff(): string {
    if (!this.selectedDiffFile) return this.diff.diff;
    return this.diff.diff.split(/(?=^diff --git )/m).find((section: string) => section.includes(` b/${this.selectedDiffFile}\n`)) || '';
  }

  get diffLines(): any[] {
    return this.currentFileDiff.split('\n').map((text: string) => ({ text, kind: text.startsWith('+') && !text.startsWith('+++') ? 'added' : text.startsWith('-') && !text.startsWith('---') ? 'removed' : text.startsWith('@@') ? 'hunk' : '' }));
  }

  get completedStageCount(): number { return this.stages.filter(stage => ['complete', 'waiting'].includes(this.stageStatus(stage.id))).length; }

  async connect(issueKey?: string): Promise<void> {
    this.connectionError = '';
    if (!this.apiToken.trim()) { this.connectionError = 'Enter the local API bearer token to connect.'; return; }
    this.connecting = true;
    this.apiUrl = this.apiUrl.trim().replace(/\/$/, '');
    try {
      await firstValueFrom(this.http.get(this.url('/health'), { headers: this.headers() }));
      this.connected = true;
      sessionStorage.setItem('ai-dlc-api-url', this.apiUrl);
      sessionStorage.setItem('ai-dlc-api-token', this.apiToken);
      const [, repositories] = await Promise.all([
        this.loadTickets(),
        firstValueFrom(this.http.get<any>(this.url('/api/repositories'), { headers: this.headers() }))
      ]);
      this.repositories = repositories.repositories || [];
      if (issueKey) this.selectTicket(this.tickets.find(ticket => ticket.key.toLowerCase() === issueKey.toLowerCase()) || null);
    } catch (error) { this.connected = false; this.connectionError = this.errorMessage(error); }
    finally { this.connecting = false; }
  }

  async loadTickets(): Promise<void> {
    this.ticketLoading = true;
    try {
      const collected: any[] = [];
      let startAt = 0;
      do {
        const params = new HttpParams().set('page_size', '100').set('start_at', String(startAt));
        const page = await firstValueFrom(this.http.get<any>(this.url('/api/jira/my-issues'), { headers: this.headers(), params }));
        collected.push(...page.issues);
        startAt = page.next_page ?? -1;
      } while (startAt >= 0);
      this.tickets = collected;
    } catch (error) { this.requestError = this.errorMessage(error); }
    finally { this.ticketLoading = false; }
  }

  selectTicket(ticket: any): void {
    this.selectedTicket = ticket;
    this.selectedRepository = ticket?.repository_candidates?.length === 1 ? ticket.repository_candidates[0] : '';
    this.targets = [];
    this.selectedTarget = '';
    this.targetError = '';
    this.targetNeedsOptIn = false;
    this.repositoryDefaultBranch = '';
    this.branches = [];
    this.baseBranch = '';
    this.branchConflict = null;
    this.reuseExistingBranch = false;
    this.branchError = '';
    this.branchName = ticket ? `ai-dlc/${ticket.key.toLowerCase()}-${crypto.randomUUID().slice(0, 8)}` : '';
    this.requestError = '';
    if (this.selectedRepository) this.loadRepository();
  }

  loadRepository(): void {
    this.branchConflict = null;
    this.reuseExistingBranch = false;
    this.branchError = '';
    void this.loadTargets();
    void this.loadBranches();
  }

  async loadTargets(): Promise<void> {
    if (!this.selectedRepository) return;
    this.targetError = '';
    this.targetNeedsOptIn = false;
    this.targets = [];
    this.selectedTarget = '';
    const [owner, name] = this.selectedRepository.split('/');
    if (!owner || !name) return;
    this.checkingTarget = true;
    try {
      const result = await firstValueFrom(this.http.get<any>(this.url(`/api/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/targets`), { headers: this.headers() }));
      this.repositoryDefaultBranch = result.default_branch || '';
      if (!result.enabled) { this.targetNeedsOptIn = true; return; }
      this.targets = result.targets || [];
      if (this.targets.length === 1) this.selectedTarget = this.targets[0].name;
    } catch (error) { this.targetError = this.errorMessage(error); }
    finally { this.checkingTarget = false; }
  }

  async loadBranches(): Promise<void> {
    if (!this.selectedRepository) return;
    const [owner, name] = this.selectedRepository.split('/');
    if (!owner || !name) return;
    try {
      const result = await firstValueFrom(this.http.get<any>(this.url(`/api/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/branches`), { headers: this.headers() }));
      this.branches = result.branches || [];
      this.baseBranch = result.default_branch || this.branches[0]?.name || '';
      this.branchConflict = null;
      this.reuseExistingBranch = false;
      await this.checkBranch();
    } catch (error) { this.branchError = this.errorMessage(error); }
  }

  async checkBranch(): Promise<void> {
    this.branchConflict = null;
    this.reuseExistingBranch = false;
    this.branchError = '';
    if (!this.selectedRepository || !this.branchName.trim() || !this.baseBranch) return;
    if (this.branchName.trim() === this.baseBranch) {
      this.branchError = 'Choose a new working branch name different from its base branch.';
      return;
    }
    const [owner, name] = this.selectedRepository.split('/');
    if (!owner || !name) return;
    this.checkingBranch = true;
    try {
      const result = await firstValueFrom(this.http.get<any>(this.url(`/api/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/branch-check`), {
        headers: this.headers(), params: new HttpParams().set('branch', this.branchName.trim()).set('base_branch', this.baseBranch),
      }));
      if (result.exists) {
        this.branchConflict = result;
        if (result.protected) this.branchError = 'This existing branch is protected. Choose an unprotected working branch name.';
      }
    } catch (error) { this.branchError = this.errorMessage(error); }
    finally { this.checkingBranch = false; }
  }

  changeBranchName(value: string): void {
    this.branchName = value;
    this.branchConflict = null;
    this.reuseExistingBranch = false;
    this.branchError = '';
  }

  chooseExistingBranch(): void { this.reuseExistingBranch = true; this.branchError = ''; }

  chooseDifferentBranch(): void {
    this.branchName = '';
    this.branchConflict = null;
    this.reuseExistingBranch = false;
    this.branchError = '';
  }

  changeBaseBranch(value: string): void {
    this.baseBranch = value;
    this.branchConflict = null;
    this.reuseExistingBranch = false;
    void this.checkBranch();
  }

  async startWorkflow(): Promise<void> {
    if (!this.selectedTicket || !this.selectedRepository || !this.selectedTarget || !this.branchName.trim() || !this.baseBranch || this.branchConflict && !this.reuseExistingBranch || this.startLoading) return;
    this.startLoading = true;
    this.requestError = '';
    try {
      const body = { jira_key: this.selectedTicket.key, repository: this.selectedRepository, target: this.selectedTarget,
        branch_name: this.branchName.trim(), base_branch: this.baseBranch, reuse_existing_branch: this.reuseExistingBranch,
        ...(this.selectedProfile ? { stack: this.selectedProfile } : {}) };
      this.run = await firstValueFrom(this.http.post<any>(this.url('/api/workflows'), body, { headers: this.headers() }));
      this.events = [];
      this.diff = { files: [], diff: '', updated_at: '' };
      this.selectedDiffFile = '';
      this.approvalComment = '';
      this.startPolling();
      await this.refreshRun();
    } catch (error: any) {
      if (error?.status === 409 && this.selectedRepository) {
        await this.checkBranch();
        if (this.branchConflict) { this.requestError = ''; return; }
      }
      this.requestError = this.errorMessage(error);
    }
    finally { this.startLoading = false; }
  }

  async decide(approved: boolean): Promise<void> {
    if (!this.run?.pending_approval || this.approvalLoading) return;
    this.approvalLoading = true;
    this.requestError = '';
    try {
      await firstValueFrom(this.http.post(this.url(`/api/workflows/${this.run.run_id}/approval`), {
        approved, approval_type: this.run.pending_approval.type, comment: this.approvalComment, approver: this.approver.trim() || 'Demo reviewer'
      }, { headers: this.headers() }));
      sessionStorage.setItem('ai-dlc-approver', this.approver.trim() || 'Demo reviewer');
      this.approvalComment = '';
      await this.refreshRun();
    } catch (error) { this.requestError = this.errorMessage(error); }
    finally { this.approvalLoading = false; }
  }

  async refreshRun(): Promise<void> {
    if (!this.run || this.polling) return;
    this.polling = true;
    try {
      const [run, eventResponse, diff] = await Promise.all([
        firstValueFrom(this.http.get<any>(this.url(`/api/workflows/${this.run.run_id}`), { headers: this.headers() })),
        firstValueFrom(this.http.get<any>(this.url(`/api/workflows/${this.run.run_id}/events`), { headers: this.headers(), params: new HttpParams().set('after', String(this.events.at(-1)?.id || 0)) })),
        firstValueFrom(this.http.get<any>(this.url(`/api/workflows/${this.run.run_id}/diff`), { headers: this.headers() }))
      ]);
      this.run = run;
      this.events = [...this.events, ...(eventResponse.events || [])];
      this.diff = diff;
      if (!this.selectedDiffFile || !diff.files.includes(this.selectedDiffFile)) this.selectedDiffFile = diff.files[0] || '';
      this.lastUpdated = new Date().toLocaleTimeString();
      if (run.phase === 'completed' || run.phase === 'failed') this.stopPolling();
    } catch (error) { this.requestError = this.errorMessage(error); }
    finally { this.polling = false; }
  }

  stageStatus(stageId: string): string {
    const approvalStage: Record<string, string> = { architecture_approval: 'human_approval', code_approval: 'code_approval', merge_approval: 'final_approval' };
    if (approvalStage[this.run?.pending_approval?.type || ''] === stageId) return 'waiting';
    if (!this.run) return 'queued';
    const records = this.events.filter((event: any) => event.stage === stageId);
    const started = [...records].reverse().find((event: any) => event.event === 'started');
    const completed = [...records].reverse().find((event: any) => event.event === 'completed');
    if (started && (!completed || started.id > completed.id)) return 'running';
    if (completed) return ['failed', 'tests_failed', 'quality_failed'].includes(completed.status) ? 'failed' : 'complete';
    if (this.run.phase === 'failed' && stageId === 'quality' && this.run.state.quality_result?.passed === false) return 'failed';
    return 'queued';
  }

  stageTime(stageId: string): string {
    const event = [...this.events].reverse().find((item: any) => item.stage === stageId);
    return event ? new Date(event.time).toLocaleTimeString() : '';
  }

  statusLabel(status: string): string {
    return ({ running: 'In progress', waiting: 'Review needed', complete: 'Complete', failed: 'Failed', queued: 'Queued' } as Record<string, string>)[status] || status;
  }

  showWorkflow(): void { this.run = null; this.events = []; this.diff = { files: [], diff: '', updated_at: '' }; this.stopPolling(); }
  clearSession(): void { this.stopPolling(); sessionStorage.removeItem('ai-dlc-api-token'); this.apiToken = ''; this.connected = false; this.tickets = []; this.repositories = []; this.run = null; }
  openPullRequest(): void { if (this.run?.state.pr_url) window.open(this.run.state.pr_url, '_blank', 'noopener,noreferrer'); }
  isApproval(type: string): boolean { return this.run?.pending_approval?.type === type; }
  private startPolling(): void { this.stopPolling(); this.pollHandle = window.setInterval(() => void this.refreshRun(), 1600); }
  private stopPolling(): void { if (this.pollHandle !== null) window.clearInterval(this.pollHandle); this.pollHandle = null; }
  private url(path: string): string { return `${this.apiUrl.replace(/\/$/, '')}${path}`; }
  private headers(): HttpHeaders { return new HttpHeaders({ Authorization: `Bearer ${this.apiToken}` }); }
  private errorMessage(error: any): string {
    const detail = error?.error?.detail;
    if (detail?.repository_candidates) return `The ticket mentions multiple repositories: ${detail.repository_candidates.join(', ')}. Select the intended repository before starting.`;
    return typeof detail === 'string' ? detail : detail?.message || error?.message || `Request failed (${error?.status || 'network'}).`;
  }
}
