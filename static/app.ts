


document.getElementById("filter-form")!.addEventListener("submit", function(event) {
    event.preventDefault();
    searchCompanies();
});
document.getElementById("reset-filters")!.addEventListener("click", function() {loadJobs();});



interface JobPosting {
    id: number;
    title: string;
    company: string;
    location: string | null;
    raw_description: string | null;
    date_posted: string | null;
    url: string;
    scraped_at: string | null;
}

interface SkillFrequency {
    skill: string;
    posting_count: number;
    percentage: number;
    mention_count: number;
}



async function getJobData(company?: string): Promise<JobPosting[]> {

    const url = company ? `/api/jobs?company=${encodeURIComponent(company)}` : "/api/jobs";

    const response = await fetch(url);

    if (!response.ok) throw new Error(`Request failed: ${response.status}`);

    return response.json();
}



async function loadJobs(): Promise<void> {

    const jobs = await getJobData();

    console.log("jobs: ", jobs);

    renderJobListings(jobs);
    renderJobKeyStats(jobs);
}



async function getSkillsData(): Promise<SkillFrequency[]> {

    const response = await fetch("/api/skills/top");

    if (!response.ok) throw new Error(`Request failed: ${response.status}`);

    return response.json();
}



async function loadSkills(): Promise<void> {

    const skills = await getSkillsData();

    console.log("skills: ", skills);

    renderSkillsChart(skills);
    renderSkillsTable(skills);
    renderSkillKeyStats(skills);
}



function formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString("en-GB",{
        day: "numeric",
        month: "short",
        year: "numeric"
    });
}



function renderJobListings(jobs: JobPosting[]) {

    const listingTable: HTMLTableElement = <HTMLTableElement>document.getElementById("jobs-tbody");

    let newJobs: HTMLTableRowElement[] = [];

    for (let job of jobs) {

        const jobRow: HTMLTableRowElement = document.createElement("tr");

        const titleCell: HTMLElement = document.createElement("td");
        titleCell.classList.toggle("text-muted", job.title === null);
        titleCell.textContent = job.title || "\u2014";


        const companyCell: HTMLElement = document.createElement("td");
        companyCell.classList.toggle("text-muted", job.company === null);
        companyCell.textContent = job.company || "\u2014";


        const locationCell: HTMLElement = document.createElement("td");
        locationCell.classList.toggle("text-muted", job.location === null);
        locationCell.textContent = job.location || "\u2014";


        const dateCell: HTMLElement = document.createElement("td");
        dateCell.classList.add("num");
        dateCell.classList.toggle("text-muted", job.date_posted === null);

        if (job.date_posted === null) {
            dateCell.textContent = "\u2014";
        } else {
            const dateCellTime: HTMLTimeElement = document.createElement("time");
            dateCellTime.dateTime = job.date_posted;
            dateCellTime.textContent = formatDate(job.date_posted);
            dateCell.appendChild(dateCellTime);
        }


        const urlCell: HTMLElement = document.createElement("td");
        urlCell.classList.add("col-action");

        const urlCellLink: HTMLElement = document.createElement("a");
        urlCellLink.classList.add("row-link");
        urlCellLink.setAttribute("href", job.url);
        urlCellLink.textContent = "View\u00A0\u2192";

        urlCell.appendChild(urlCellLink);


        jobRow.appendChild(titleCell);
        jobRow.appendChild(companyCell);
        jobRow.appendChild(locationCell);
        jobRow.appendChild(dateCell);
        jobRow.appendChild(urlCell);

        newJobs.push(jobRow);
    }

    listingTable.replaceChildren(...newJobs);
}



function renderJobKeyStats(jobs: JobPosting[]) {

    document.querySelector("[data-field='total-postings']")!.textContent = String(jobs.length);

    let uniqueCompanies: Set<string> = new Set(jobs.map(j => j.company));

    document.querySelector("[data-field='total-companies']")!.textContent = String(uniqueCompanies.size);
}



function renderSkillsChart(skills: SkillFrequency[]) {

    // get skills chart element as a variable
    const skillsChart: HTMLDivElement = <HTMLDivElement>document.getElementById("skills-chart");

    let newSkills: HTMLDivElement[] = [];

    for (let newSkill of skills) {

        const maxPostingCount: number = Math.max(...skills.map(s => s.posting_count));

        const widthPercent: number = (newSkill.posting_count / maxPostingCount) * 100;


        const skillRow: HTMLDivElement = document.createElement("div");
        skillRow.classList.add("skill-row");


        const skillName: HTMLSpanElement = document.createElement("span");
        skillName.classList.add("skill-name");
        skillName.textContent = newSkill.skill;


        const skillBarTrack: HTMLSpanElement = document.createElement("span");
        skillBarTrack.classList.add("skill-bar-track");

        const skillBar: HTMLSpanElement = document.createElement("span");
        skillBar.classList.add("skill-bar");
        skillBar.style.width = `${widthPercent}%`
        skillBar.title = `${newSkill.skill} — ${newSkill.posting_count} of ${skills.length} postings (${newSkill.percentage}%)`;

        skillBarTrack.appendChild(skillBar);


        const skillValue: HTMLSpanElement = document.createElement("span");
        skillValue.classList.add("skill-value");
        skillValue.textContent = `${newSkill.percentage}%`;


        skillRow.appendChild(skillName);
        skillRow.appendChild(skillBarTrack);
        skillRow.appendChild(skillValue);

        newSkills.push(skillRow);
    }

    skillsChart.replaceChildren(...newSkills);
}



function renderSkillsTable(skills: SkillFrequency[]) {

    // create this during the next coding session
    const skillsTable: HTMLTableElement = <HTMLTableElement>document.getElementById("skills-tbody");

    let newSkills: HTMLTableRowElement[] = [];

    for (let newSkill of skills) {

        const skillRow: HTMLTableRowElement = document.createElement("tr");


        const skillName: HTMLTableCellElement = document.createElement("td");
        skillName.textContent = newSkill.skill;


        const skillPostings: HTMLTableCellElement = document.createElement("td");
        skillPostings.classList.add("num");
        skillPostings.textContent = String(newSkill.posting_count);


        const skillPercentage: HTMLTableCellElement = document.createElement("td");
        skillPercentage.classList.add("num");
        skillPercentage.textContent = String(newSkill.percentage);


        skillRow.appendChild(skillName);
        skillRow.appendChild(skillPostings);
        skillRow.appendChild(skillPercentage);

        newSkills.push(skillRow);
    }

    skillsTable.replaceChildren(...newSkills);
}



function renderSkillKeyStats(skills: SkillFrequency[]) {

    document.querySelector("[data-field='top-skill']")!.textContent = String(skills[0]!.skill);

    document.querySelector("[data-field='skills-tracked']")!.textContent = String(skills.length);
}



async function searchCompanies(): Promise<void> {

    const input: HTMLInputElement = <HTMLInputElement>document.getElementById("company-filter");
    const company: string = input.value.trim();

    const jobs = await getJobData(company || undefined);

    renderJobListings(jobs);
    renderJobKeyStats(jobs);
}



document.addEventListener("DOMContentLoaded", () => {
    loadJobs();
    loadSkills();
});



console.log("app.ts loaded");