import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { AppComponent } from './app.component';

describe('AppComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [provideHttpClient()],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('lists only matching assigned tickets', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    app.tickets = [
      { key: 'APP-12', summary: 'Angular payment banner', description: '', repository_candidates: [] },
      { key: 'API-4', summary: 'Customer endpoint', description: '', repository_candidates: [] },
    ];
    app.ticketFilter = 'angular';
    expect(app.filteredTickets.map(ticket => ticket.key)).toEqual(['APP-12']);
  });

  it('requires a repository choice when a ticket has conflicting references', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    app.repositories = [{ full_name: 'RogersCommunications/fallback' }];
    app.selectedTicket = { repository_candidates: [
      'RogersCommunications/api', 'RogersCommunications/ui',
    ] };
    expect(app.repositoryOptions).toEqual([
      'RogersCommunications/api', 'RogersCommunications/ui',
    ]);
    expect(app.selectedRepository).toBe('');
  });

  it('renders the workflow console', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('h1')?.textContent).toContain('From ticket to pull request');
  });
});
